"""Curated output-field catalogue for the four user-supplied SQL views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CatalogField:
    expression: str
    description: str


@dataclass(frozen=True, slots=True)
class ViewCatalog:
    active: bool
    description: str
    fields: dict[str, CatalogField]


CONTRACT_AGGREGATE_FIELDS = {
    "ddid": CatalogField("uf_dd.id", "OA 订单 ID"),
    "count_all": CatalogField("COUNT(*)", "订单纳入判断的合同数量"),
    "count_meet": CatalogField(
        "COUNT(CASE WHEN ismeet=1 THEN 1 END)",
        "满足合同条件的合同数量",
    ),
    "count_nomeet": CatalogField(
        "COUNT(CASE WHEN ismeet=0 THEN 1 END)",
        "不满足合同条件的合同数量",
    ),
    "dd_ismeet": CatalogField(
        "CASE WHEN count_all=0 OR count_nomeet>0 THEN 0 ELSE 1 END",
        "订单全部合同条件是否通过",
    ),
}


VIEW_FIELD_CATALOG: dict[str, ViewCatalog] = {
    "v_DataReleaseSealCondition": ViewCatalog(
        active=False,
        description="原始数据释放合同条件；当前两个主视图中的关联和筛选已注释",
        fields=CONTRACT_AGGREGATE_FIELDS,
    ),
    "v_OrderFormaltestsettlement": ViewCatalog(
        active=True,
        description="正式实验任务的预估完工费、确认结算费和订单上下文",
        fields={
            "dd": CatalogField("uf_zssyrwtz.dd", "订单 ID"),
            "sqlc": CatalogField("uf_zssyrwtz.sqlc", "正式实验任务流程号"),
            "zssywgfy": CatalogField(
                "SUM(COALESCE(wcsl, xdsl) * uf_dd_dt1.yhhdj)",
                "正式实验任务预估完工费",
            ),
            "bcjsfy": CatalogField(
                "ROUND(SUM(bcjsfy * wgfy / NULLIF(jsfyhj,0) - jmje),2)",
                "已确认结算单分摊后的本次结算费",
            ),
            "zssyjsfy": CatalogField(
                "CASE WHEN bcjsfy IS NULL THEN COALESCE(zssywgfy,0) ELSE bcjsfy END",
                "正式实验任务最终采用费用",
            ),
            "ddbh": CatalogField("uf_dd.ddbh", "订单编号"),
            "ht": CatalogField("uf_dd.ht", "订单合同字段"),
            "yhhje": CatalogField("COALESCE(uf_dd.yhhje,0)", "订单金额"),
            "sfdls": CatalogField("COALESCE(uf_dd.sfdls,1)", "是否框架协议"),
            "gsmc": CatalogField("uf_dd.gsmc", "公司名称"),
            "khdw": CatalogField("uf_dd.khdw", "客户单位"),
            "sfgykh": CatalogField("COALESCE(uf_dd.sfgykh,1)", "是否工业客户"),
            "khjl": CatalogField("uf_dd.khjl", "客户经理"),
            "cpmc": CatalogField("uf_dd.cpmc", "产品名称"),
            "cjly": CatalogField("uf_dd.cjly", "创建来源"),
            "gzcrmzxht": CatalogField("uf_dd.gzcrmzxht", "执行合同 ID"),
            "xmlxrcrm": CatalogField("uf_dd.xmlxrcrm", "项目联系人 ID"),
            "wtdlr": CatalogField("uf_dd.wtdlr", "委托代理人 ID"),
            "wtdlrsjh": CatalogField("uf_dd.khdh", "委托代理人手机号"),
            "wtdlrxm": CatalogField("uf_customer.khxm", "委托代理人姓名"),
            "wtdlryx": CatalogField("uf_dd.khyx", "委托代理人邮箱"),
            "xmlxr1": CatalogField("uf_dd.xmlxrcrm", "项目联系人 ID 别名"),
            "xmlxrxm": CatalogField("uf_uf_contacts.lxrxm", "项目联系人姓名"),
            "xmlxrsjh": CatalogField("uf_dd.sqlxrdh", "项目联系人手机号"),
            "xmlxryx": CatalogField("uf_dd.sqlxryx", "项目联系人邮箱"),
        },
    ),
    "v_ReportDataReleaseRules": ViewCatalog(
        active=True,
        description="报告跨订单费用与订单累计关联金额辅助视图",
        fields={
            "ddgldk": CatalogField("v_sto.ddgldk", "订单关联普通到款"),
            "dkbl": CatalogField("v_sto.dkbl", "到款比例"),
            "ddglyj": CatalogField("v_sto.ddglyj", "订单关联押金"),
            "yjbl": CatalogField("v_sto.yjbl", "押金比例"),
            "ddgldk_total": CatalogField("ddgldk + ddglyj", "订单累计关联金额，包含押金"),
            "bgsffy": CatalogField(
                "SUM(v_OrderFormaltestsettlement.zssyjsfy) FROM uf_xmbgsf WHERE zt<>2",
                "已进入报告释放范围的正式实验费用",
            ),
            "bgsffy80": CatalogField("bgsffy * 0.8", "报告释放费用的 80%"),
            "sjsffy": CatalogField(
                "SUM(v_OrderFormaltestsettlement.zssyjsfy) FROM uf_yssjsf WHERE zt<>2",
                "已进入原始数据释放范围的正式实验费用",
            ),
            "zssywgfy": CatalogField(
                "ROUND(SUM(COALESCE(wcsl,xdsl) * uf_dd_dt1.yhhdj),2)",
                "订单下正式实验预估完工费",
            ),
            "ctwgfy": CatalogField(
                "ROUND(SUM(COALESCE(wcsl,xdsl) * uf_dd_dt1.yhhdj),2)",
                "订单下承接转交预估完工费",
            ),
            "wgfy_total": CatalogField("zssywgfy + ctwgfy", "订单预估完工费合计"),
            "ddwgldk_total": CatalogField(
                "zssywgfy + ctwgfy - ddgldk - ddglyj",
                "预估完工费扣除累计关联金额后的差额",
            ),
            "ddwgldk_total20": CatalogField(
                "(zssywgfy + ctwgfy - ddgldk - ddglyj) * 0.2",
                "未覆盖完工费差额的 20%",
            ),
            "ctzjjsfy": CatalogField(
                "SUM(COALESCE(confirmed_settlement, ctwgfy))",
                "承接转交任务最终采用费用",
            ),
        },
    ),
    "v_ReportReleaseSealCondition": ViewCatalog(
        active=True,
        description="项目报告释放合同盖章/签署条件",
        fields=CONTRACT_AGGREGATE_FIELDS,
    ),
}


def resolve_catalog_field(
    view_name: str,
    view_field: str,
) -> tuple[ViewCatalog, CatalogField] | None:
    view = VIEW_FIELD_CATALOG.get(view_name)
    if view is None:
        return None
    field = view.fields.get(view_field)
    if field is None:
        return None
    return view, field


def catalog_for_prompt() -> dict[str, Any]:
    return {
        view_name: {
            "active": view.active,
            "description": view.description,
            "fields": {
                field_name: {
                    "sourceExpression": field.expression,
                    "description": field.description,
                }
                for field_name, field in view.fields.items()
            },
        }
        for view_name, view in VIEW_FIELD_CATALOG.items()
    }
