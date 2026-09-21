"""Build a portable Tableau Public workbook from the exported CSV package.

The Tableau XML format is intentionally kept small: one presentation-ready
CSV powers all sheets, avoiding cross-fact joins that can duplicate values.
"""

from __future__ import annotations

import csv
import shutil
import zipfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "tableau"
BUILD = SOURCE / "workbook"
DATA_FILE = BUILD / "Data" / "eu_wholesale_dashboard.csv"
HYPER_FILE = BUILD / "Data" / "Extracts" / "eu_wholesale_dashboard.hyper"
TWB_FILE = BUILD / "EU_Wholesale_Analytics.twb"
PACKAGE = SOURCE / "EU_Wholesale_Analytics.twbx"


def read_csv(name: str) -> list[dict[str, str]]:
    with (SOURCE / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(value: str | None) -> float:
    return float(value or 0)


def month_date(value: str) -> str:
    return f"{value}-01"


FIELDS = [
    "view_type", "date", "country_code", "country_name", "product_id",
    "product_name", "series", "scenario", "model", "horizon",
    "category", "value", "actual", "abs_error", "metric_order",
]


def build_data() -> None:
    countries = {r["country_code"]: r["country_name"] for r in read_csv("dim_country.csv")}
    products = {r["product_id"]: r["product_name"] for r in read_csv("dim_product.csv")}
    rows: list[dict[str, object]] = []

    def add(**values: object) -> None:
        row = {field: "" for field in FIELDS}
        row.update(values)
        rows.append(row)

    actual_month: dict[tuple[str, str, str], float] = defaultdict(float)
    actual_margin: dict[tuple[str, str, str], float] = defaultdict(float)
    for row in read_csv("fact_revenue.csv"):
        key = (row["year_month"], row["country_code"], row["product_id"])
        actual_month[key] += number(row["revenue_eur"])
        actual_margin[key] += number(row["margin_eur"])
    for (month, country, product), revenue in actual_month.items():
        add(view_type="Trend", date=month_date(month), country_code=country,
            country_name=countries[country], product_id=product,
            product_name=products[product], series="Actual", value=round(revenue, 2))

    for row in read_csv("fact_forecast.csv"):
        add(view_type="Trend", date=month_date(row["year_month"]),
            country_code=row["country_code"], country_name=countries[row["country_code"]],
            product_id=row["product_id"], product_name=products[row["product_id"]],
            series="Forecast", model=row["model"], horizon=row["horizon"],
            value=round(number(row["forecast_eur"]), 2))

    latest_month = max(key[0] for key in actual_month)
    country_mix: dict[str, float] = defaultdict(float)
    product_mix: dict[str, float] = defaultdict(float)
    for (month, country, product), revenue in actual_month.items():
        if month >= f"{int(latest_month[:4]) - 1}-{latest_month[5:]}":
            country_mix[country] += revenue
            product_mix[product] += revenue
    for code, revenue in country_mix.items():
        add(view_type="Country Mix", category=countries[code], country_code=code,
            country_name=countries[code], value=round(revenue, 2))
    for code, revenue in product_mix.items():
        add(view_type="Product Mix", category=products[code], product_id=code,
            product_name=products[code], value=round(revenue, 2))

    for row in read_csv("fact_scenario.csv"):
        add(view_type="Scenario", date=month_date(row["year_month"]),
            country_code=row["country_code"], country_name=countries[row["country_code"]],
            product_id=row["product_id"], product_name=products[row["product_id"]],
            scenario=row["scenario"], series=row["scenario"], model=row["model"],
            horizon=row["horizon"], value=round(number(row["forecast_eur"]), 2))

    accuracy: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for row in read_csv("fact_backtest.csv"):
        accuracy[row["model"]][0] += number(row["abs_error"])
        accuracy[row["model"]][1] += number(row["y"])
    for model, (absolute_error, actual) in accuracy.items():
        add(view_type="Accuracy", category=model.replace("_", " ").title(),
            model=model, value=absolute_error / actual, actual=actual,
            abs_error=absolute_error)

    latest_revenue = sum(v for (m, _, _), v in actual_month.items() if m == latest_month)
    latest_margin = sum(v for (m, _, _), v in actual_margin.items() if m == latest_month)
    prior_month = f"{int(latest_month[:4]) - 1}-{latest_month[5:]}"
    prior_revenue = sum(v for (m, _, _), v in actual_month.items() if m == prior_month)
    kpis = [
        (1, "Latest monthly revenue", latest_revenue / 1_000_000),
        (2, "YoY revenue growth", latest_revenue / prior_revenue - 1 if prior_revenue else 0),
        (3, "Gross margin", latest_margin / latest_revenue if latest_revenue else 0),
    ]
    for order, label, value in kpis:
        add(view_type="KPI", category=label, value=value, metric_order=order)

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def build_hyper() -> None:
    """Create the extract required by Tableau Public."""
    try:
        from tableauhyperapi import (
            Connection, CreateMode, HyperProcess, Inserter, SqlType,
            TableDefinition, TableName, Telemetry,
        )
    except ImportError as exc:
        raise RuntimeError(
            "tableauhyperapi is required; install it with "
            "'python -m pip install tableauhyperapi'"
        ) from exc

    table_name = TableName("Extract", "Extract")
    text_fields = set(FIELDS) - {"date", "value", "actual", "abs_error", "horizon", "metric_order"}
    columns = []
    for field in FIELDS:
        sql_type = (
            SqlType.text() if field in text_fields else
            SqlType.date() if field == "date" else
            SqlType.big_int() if field in {"horizon", "metric_order"} else
            SqlType.double()
        )
        columns.append(TableDefinition.Column(field, sql_type))

    HYPER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as process:
        with Connection(process.endpoint, str(HYPER_FILE), CreateMode.CREATE_AND_REPLACE) as connection:
            connection.catalog.create_schema("Extract")
            connection.catalog.create_table(TableDefinition(table_name, columns))
            with DATA_FILE.open(newline="", encoding="utf-8") as handle, Inserter(connection, table_name) as inserter:
                converted = []
                for row in csv.DictReader(handle):
                    values = []
                    for field in FIELDS:
                        raw = row[field]
                        if not raw:
                            values.append(None)
                        elif field == "date":
                            values.append(date.fromisoformat(raw))
                        elif field in {"value", "actual", "abs_error"}:
                            values.append(float(raw))
                        elif field in {"horizon", "metric_order"}:
                            values.append(int(raw))
                        else:
                            values.append(raw)
                    converted.append(values)
                inserter.add_rows(converted)
                inserter.execute()


def column_xml(name: str, datatype: str, role: str, col_type: str,
               aggregation: str | None = None, caption: str | None = None) -> str:
    attrs = [f"datatype='{datatype}'", f"name='[{name}]'", f"role='{role}'", f"type='{col_type}'"]
    if aggregation:
        attrs.append(f"aggregation='{aggregation}'")
    if caption:
        attrs.append(f"caption='{escape(caption)}'")
    return "<column " + " ".join(attrs) + " />"


DIMENSIONS = {
    "view_type": "View Type", "country_code": "Country Code", "country_name": "Country",
    "product_id": "Product ID", "product_name": "Product", "series": "Series",
    "scenario": "Scenario", "model": "Model", "category": "Category",
}


def dependencies(fields: list[str]) -> str:
    parts = []
    for field in fields:
        if field == "date":
            parts.append(column_xml(field, "date", "dimension", "quantitative", caption="Month"))
        elif field in {"value", "actual", "abs_error"}:
            parts.append(column_xml(field, "real", "measure", "quantitative", "Sum", field.replace("_", " ").title()))
        elif field in {"horizon", "metric_order"}:
            parts.append(column_xml(field, "integer", "dimension", "ordinal", caption=field.replace("_", " ").title()))
        else:
            parts.append(column_xml(field, "string", "dimension", "nominal", caption=DIMENSIONS.get(field, field.title())))
    return "\n".join(parts)


def worksheet(name: str, title: str, fields: list[str], rows: str, cols: str,
              mark: str, encodings: str, view_filter: str) -> str:
    deps = dependencies(fields)
    return f"""
    <worksheet name='{escape(name)}'>
      <layout-options><title><formatted-text><run bold='true' fontcolor='#183B56' fontsize='14'>{escape(title)}</run></formatted-text></title></layout-options>
      <table>
        <view>
          <datasources><datasource caption='EU Wholesale Dashboard' name='dashboard_data' /></datasources>
          <datasource-dependencies datasource='dashboard_data'>{deps}</datasource-dependencies>
          <filter class='categorical' column='[dashboard_data].[view_type]'><groupfilter function='member' level='[view_type]' member='&quot;{escape(view_filter)}&quot;' /></filter>
          <slices><column>[dashboard_data].[view_type]</column></slices><aggregation value='true' />
        </view>
        <style><style-rule element='worksheet'><format attr='color' value='#FFFFFF' /></style-rule><style-rule element='axis'><format attr='color' value='#486581' /></style-rule></style>
        <panes><pane><view><breakdown value='auto' /></view><mark class='{mark}' /><encodings>{encodings}</encodings></pane></panes>
        <rows>{rows}</rows><cols>{cols}</cols>
      </table>
    </worksheet>"""


def build_twb() -> None:
    metadata = "\n".join(
        f"<metadata-record class='column'><remote-name>{f}</remote-name><remote-type>{'5' if f in {'value','actual','abs_error'} else '20' if f in {'horizon','metric_order'} else '7' if f == 'date' else '129'}</remote-type><local-name>[{f}]</local-name><parent-name>[Extract]</parent-name><remote-alias>{f}</remote-alias><ordinal>{i}</ordinal><local-type>{'real' if f in {'value','actual','abs_error'} else 'integer' if f in {'horizon','metric_order'} else 'date' if f == 'date' else 'string'}</local-type><aggregation>{'Sum' if f in {'value','actual','abs_error'} else 'Count'}</aggregation><contains-null>true</contains-null></metadata-record>"
        for i, f in enumerate(FIELDS)
    )
    sheets = [
        worksheet("KPI Summary", "Executive snapshot", ["view_type", "category", "value", "metric_order"],
                  "[dashboard_data].[category]", "[dashboard_data].[value]", "Text",
                  "<text column='[dashboard_data].[value]' />", "KPI"),
        worksheet("Revenue Trend", "Actual and forecast revenue", ["view_type", "date", "series", "value", "country_name", "product_name"],
                  "[dashboard_data].[value]", "[dashboard_data].[date]", "Line",
                  "<color column='[dashboard_data].[series]' /><lod column='[dashboard_data].[series]' />", "Trend"),
        worksheet("Country Mix", "Revenue by market — rolling 12 months", ["view_type", "category", "value", "country_name"],
                  "[dashboard_data].[category]", "[dashboard_data].[value]", "Bar",
                  "<color column='[dashboard_data].[value]' /><text column='[dashboard_data].[value]' />", "Country Mix"),
        worksheet("Product Mix", "Revenue by product — rolling 12 months", ["view_type", "category", "value", "product_name"],
                  "[dashboard_data].[category]", "[dashboard_data].[value]", "Bar",
                  "<color column='[dashboard_data].[value]' /><text column='[dashboard_data].[value]' />", "Product Mix"),
        worksheet("Scenario Comparison", "Baseline, upside and downside", ["view_type", "date", "scenario", "value", "country_name", "product_name"],
                  "[dashboard_data].[value]", "[dashboard_data].[date]", "Line",
                  "<color column='[dashboard_data].[scenario]' /><lod column='[dashboard_data].[scenario]' />", "Scenario"),
        worksheet("Forecast Accuracy", "Backtest WAPE by model", ["view_type", "category", "value", "model"],
                  "[dashboard_data].[category]", "[dashboard_data].[value]", "Bar",
                  "<color column='[dashboard_data].[value]' /><text column='[dashboard_data].[value]' />", "Accuracy"),
    ]
    zones = """
        <zone h='100000' id='1' type='layout-basic' w='100000' x='0' y='0'>
          <zone h='6500' id='2' type='title' w='100000' x='0' y='0' />
          <zone h='11500' id='3' name='KPI Summary' show-title='true' w='100000' x='0' y='6500' />
          <zone h='39000' id='4' name='Revenue Trend' show-title='true' w='60000' x='0' y='18000' />
          <zone h='39000' id='5' name='Scenario Comparison' show-title='true' w='40000' x='60000' y='18000' />
          <zone h='43000' id='6' name='Country Mix' show-title='true' w='33000' x='0' y='57000' />
          <zone h='43000' id='7' name='Product Mix' show-title='true' w='34000' x='33000' y='57000' />
          <zone h='43000' id='8' name='Forecast Accuracy' show-title='true' w='33000' x='67000' y='57000' />
        </zone>"""
    xml = f"""<?xml version='1.0' encoding='utf-8'?>
<!-- Generated {datetime.now().isoformat(timespec='seconds')} -->
<workbook locale='en_GB' source-build='2026.2.2' source-platform='mac' version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <document-format-change-manifest>
    <_.fcp.ObjectModelEncapsulateLegacy.true...ObjectModelEncapsulateLegacy />
    <_.fcp.ObjectModelTableType.true...ObjectModelTableType />
    <_.fcp.SchemaViewerObjectModel.true...SchemaViewerObjectModel />
  </document-format-change-manifest>
  <preferences><preference name='ui.encoding.shelf.height' value='24' /><preference name='ui.shelf.height' value='26' /></preferences>
  <style-theme name='smooth' />
  <datasources>
    <datasource caption='EU Wholesale Dashboard' inline='true' name='dashboard_data' version='18.1'>
      <connection class='federated'><named-connections><named-connection caption='EU Wholesale Dashboard Extract' name='hyper_connection'><connection authentication='auth-none' class='hyper' dbname='Data/Extracts/eu_wholesale_dashboard.hyper' default-settings='yes' schema='Extract' sslmode='' username='tableau_internal_user' /></named-connection></named-connections>
        <_.fcp.ObjectModelEncapsulateLegacy.false...relation connection='hyper_connection' name='Extract' table='[Extract].[Extract]' type='table' />
        <_.fcp.ObjectModelEncapsulateLegacy.true...relation connection='hyper_connection' name='Extract' table='[Extract].[Extract]' type='table' />
        <metadata-records>{metadata}</metadata-records>
      </connection>
      <column caption='Revenue / Value' datatype='real' datatype-customized='true' default-format='c$#,##0,,\M;-c$#,##0,,\M' name='[value]' role='measure' type='quantitative' />
      <_.fcp.ObjectModelEncapsulateLegacy.true...object-graph>
        <objects><object caption='EU Wholesale Dashboard' id='EU Wholesale Dashboard'><properties context=''><relation connection='hyper_connection' name='Extract' table='[Extract].[Extract]' type='table' /></properties></object></objects>
      </_.fcp.ObjectModelEncapsulateLegacy.true...object-graph>
    </datasource>
  </datasources>
  <worksheets>{''.join(sheets)}</worksheets>
  <dashboards><dashboard name='EU Wholesale Overview'><layout-options><title><formatted-text><run bold='true' fontcolor='#102A43' fontsize='20'>EU Wholesale Market Analytics</run><run fontcolor='#627D98' fontsize='11'>   Actuals through June 2026 | 12-month forecast and scenarios</run></formatted-text></title></layout-options><size maxheight='900' maxwidth='1440' minheight='900' minwidth='1440' /><datasources><datasource caption='EU Wholesale Dashboard' name='dashboard_data' /></datasources><zones>{zones}</zones></dashboard></dashboards>
  <windows source-height='32'><window class='dashboard' maximized='true' name='EU Wholesale Overview'><viewpoints>{''.join(f"<viewpoint name='{n}' />" for n in ['KPI Summary','Revenue Trend','Country Mix','Product Mix','Scenario Comparison','Forecast Accuracy'])}</viewpoints><active id='-1' /></window></windows>
</workbook>
"""
    TWB_FILE.write_text(xml, encoding="utf-8")


def package() -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    build_data()
    build_hyper()
    build_twb()
    with zipfile.ZipFile(PACKAGE, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(TWB_FILE, TWB_FILE.name)
        archive.write(HYPER_FILE, f"Data/Extracts/{HYPER_FILE.name}")


if __name__ == "__main__":
    package()
    print(PACKAGE)
