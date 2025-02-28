# -*- coding: utf-8 -*-
"""
TencentBlueKing is pleased to support the open source community by making
蓝鲸智云 - Resource SDK (BlueKing - Resource SDK) available.
Copyright (C) 2022 THL A29 Limited,
a Tencent company. All rights reserved.
Licensed under the MIT License (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at http://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
either express or implied. See the License for the
specific language governing permissions and limitations under the License.
We undertake not to change the open source license (MIT license) applicable
to the current version of the project delivered to anyone in the future.
"""
from dataclasses import dataclass

from apm_web.constants import CategoryEnum, QueryMode
from apm_web.handlers.trace_handler.base import (
    SpanPredicate,
    StatusCodeAttributePredicate,
)
from django.utils.translation import ugettext_lazy as _
from elasticsearch_dsl import Q, Search
from luqum.auto_head_tail import auto_head_tail
from luqum.elasticsearch import ElasticsearchQueryBuilder, SchemaAnalyzer
from luqum.exceptions import ParseError
from luqum.parser import lexer, parser
from luqum.tree import SearchField, Word
from luqum.visitor import TreeTransformer
from opentelemetry.trace import StatusCode

from bkmonitor.utils.elasticsearch.handler import BaseTreeTransformer
from constants.apm import OtlpKey, SpanKind
from core.drf_resource import api
from core.errors.alert import QueryStringParseError


class QueryBuilder(ElasticsearchQueryBuilder):
    """
    Elasticsearch query_string 到 DSL 转换器
    """

    def _yield_nested_children(self, parent, children):
        for child in children:
            # 同级语句同时出现 AND 与 OR 时，忽略默认的报错
            yield child


class QueryTreeTransformer(BaseTreeTransformer):

    # 需要转换的嵌套KV字段，key 为匹配前缀，value 为搜索字段
    NESTED_KV_FIELDS = {}

    # 嵌套字段配置 用于用户查询时进行DSL转换
    NESTED_FIELDS_CONFIG = {}

    # 需要进行值转换的字段
    VALUE_TRANSLATE_FIELDS = {}

    DOC_SCHEMA = {}

    @classmethod
    def get_doc_simple_schema(cls):
        # 在没有完整schema的情况下 只需要知道哪些是嵌套字段 就可以准确查询
        return {"settings": {}, "mappings": {"properties": {**cls.NESTED_FIELDS_CONFIG}}}

    @classmethod
    def get_doc_schema(cls):
        return

    @classmethod
    def transform_field_to_es_field(cls, field: str, for_agg=False):
        return field

    def visit_search_field(self, node, context):
        if context.get("ignore_search_field"):
            yield from self.generic_visit(node, context)
        else:
            origin_node_name = node.name
            for field, es_field in self.NESTED_KV_FIELDS.items():
                if node.name.startswith(f"{field}."):
                    self.has_nested_field = True
                    break
            else:
                node = SearchField(self.transform_field_to_es_field(node.name), node.expr)
            yield from self.generic_visit(
                node, {"search_field_name": node.name, "search_field_origin_name": origin_node_name}
            )

    @classmethod
    def generate_query(cls, origin_search_object, query_string: str) -> Search:
        if not query_string:
            return origin_search_object

        try:
            query_tree = parser.parse(query_string, lexer=lexer)
        except ParseError as e:
            raise QueryStringParseError({"msg": e})

        if str(query_tree) == "*":
            # 如果只有一个* es特殊符号不需要作为字符串处理
            return origin_search_object.query("query_string", query="*")

        transformer = cls()
        query_tree = transformer.visit(query_tree)

        if getattr(transformer, "has_nested_field", False):
            if cls.DOC_SCHEMA:
                schema_analyzer = SchemaAnalyzer(cls.DOC_SCHEMA)
            else:
                schema_analyzer = SchemaAnalyzer(cls.get_doc_simple_schema())

            es_builder = QueryBuilder(**schema_analyzer.query_builder_options())
            return origin_search_object.query(es_builder(query_tree))

        # 手动修改后的语法数可能会有一些空格丢失的问题，因此需要对树的头尾进行重整
        query_tree = auto_head_tail(query_tree)

        if isinstance(query_tree, Word):
            # 纯文本搜索需要加上嵌套字段作为or条件
            keyword_filter = Q("query_string", query=str(query_tree))
            nested_filters = []
            for i in cls.NESTED_KV_FIELDS.values():
                nested_filters.append(Q("nested", path=i, query=keyword_filter))

            origin_search_object = origin_search_object.query("bool", should=[keyword_filter] + nested_filters)
        else:
            origin_search_object = origin_search_object.query("query_string", query=str(query_tree))

        return origin_search_object


class SpanQueryTransformer(QueryTreeTransformer):

    NESTED_KV_FIELDS = {"events": "events", "links": "links"}

    # 嵌套字段配置 用于用户查询时进行DSL转换
    NESTED_FIELDS_CONFIG = {
        "events": {
            "properties": {
                "exception": {"properties": {"message": {"type": "text"}, "stacktrace": {"type": "text"}}},
                "timestamp": {"type": "long"},
            },
            "type": "nested",
        },
        "links": {"properties": {"span_id": {"type": "string"}}, "type": "nested"},
    }


class TraceQueryTransformer(QueryTreeTransformer):

    NESTED_KV_FIELDS = {}

    # 嵌套字段配置 用于用户查询时进行DSL转换
    NESTED_FIELDS_CONFIG = {}

    PRE_CALC_STANDARD_FIELD_PREFIX = "collections"

    DIRECT_FIELD_NAME_MAPPING = {
        "span_name": f"{PRE_CALC_STANDARD_FIELD_PREFIX}.span_name",
        "kind": f"{PRE_CALC_STANDARD_FIELD_PREFIX}.kind",
    }

    @classmethod
    def transform_field_to_es_field(cls, field: str, for_agg=False):
        if field in cls.DIRECT_FIELD_NAME_MAPPING:
            return cls.DIRECT_FIELD_NAME_MAPPING[field]

        # attribute, resource 也需要转换
        if field.startswith(OtlpKey.ATTRIBUTES) or field.startswith(OtlpKey.RESOURCE):
            return f"{cls.PRE_CALC_STANDARD_FIELD_PREFIX}.{field}"

        return field


class FieldTransformer(TreeTransformer):

    # 如果filters包含这个字段 需要忽略 因为duration字段在TRACE/span检索中有特殊处理
    FILTERS_IGNORE_FIELDS = ["duration"]

    def __init__(self, fields, opposite=False, *args, **kwargs):
        super(FieldTransformer, self).__init__(*args, **kwargs)
        self.is_has_field_not_in_fields = False
        self.fields = fields
        self.opposite = opposite

    def visit_search_field(self, node, _):

        if not self.opposite:
            if node.name not in self.fields:
                self.is_has_field_not_in_fields = True
        else:
            if node.name in self.fields:
                self.is_has_field_not_in_fields = True

        yield node

    def has_file_not_in_filters(self, filters):

        all_fields = self.FILTERS_IGNORE_FIELDS + self.fields

        for i in filters:
            if not self.opposite:
                if i["key"] not in all_fields:
                    return True
            else:
                if i["key"] in all_fields:
                    return True
        return False


class OptionValues:

    API = None
    FIELDS = []

    class Source:
        """数据来源"""

        # 从方法中获取
        METHOD = "method"
        # 从ES中获取
        ES = "es"

    @dataclass
    class Field:
        # 需要获取候选值的字段
        id: str
        source: str
        label: str

    def __init__(self, bk_biz_id, app_name):
        self.bk_biz_id = bk_biz_id
        self.app_name = app_name

    @classmethod
    def get_option_values(cls, option: "OptionValues", start_time, end_time):
        res = {}
        query_es_fields = []
        for field in option.FIELDS:
            if field.source == OptionValues.Source.METHOD:
                res[field.id] = getattr(option, f"get_{field.id.replace('.', '_')}")()
            else:
                query_es_fields.append(field.id)

        params = {
            "bk_biz_id": option.bk_biz_id,
            "app_name": option.app_name,
            "start_time": start_time,
            "end_time": end_time,
            "fields": query_es_fields,
        }

        value_from_es = option.API(params)
        if not value_from_es:
            return res

        # 处理ES数据保持格式一致
        for field_name, field_values in value_from_es.items():
            res[field_name] = [{"value": i, "text": i} for i in field_values]

        return res

    @classmethod
    def get_field_option_values(cls, option, fields, start_time, end_time):

        params = {
            "bk_biz_id": option.bk_biz_id,
            "app_name": option.app_name,
            "start_time": start_time,
            "end_time": end_time,
            "fields": fields,
        }

        res = {}
        value_from_es = option.API(params)
        if not value_from_es:
            return res

        for field_name, field_values in value_from_es.items():
            res[field_name] = [{"value": i, "text": i} for i in field_values]

        return res


class TraceOptionValues(OptionValues):

    API = api.apm_api.query_trace_option_values

    FIELDS = [
        OptionValues.Field(id="root_service", source=OptionValues.Source.ES, label=_("入口服务")),
        OptionValues.Field(id="root_service_span_name", source=OptionValues.Source.ES, label=_("入口接口")),
        OptionValues.Field(id="root_service_status_code", source=OptionValues.Source.ES, label=_("入口状态码")),
        OptionValues.Field(id="root_service_category", source=OptionValues.Source.METHOD, label=_("入口类型")),
        OptionValues.Field(id="root_span_name", source=OptionValues.Source.ES, label=_("根Span接口")),
        OptionValues.Field(id="root_span_service", source=OptionValues.Source.ES, label=_("根Span服务")),
    ]

    def get_root_service_category(self):
        res = []
        for i in CategoryEnum.get_filter_fields():
            if i["id"] == CategoryEnum.ALL:
                continue
            res.append({"value": i["id"], "text": i["name"]})

        return res


class SpanOptionValues(OptionValues):

    API = api.apm_api.query_span_option_values

    FIELDS = [
        OptionValues.Field(id="span_name", source=OptionValues.Source.ES, label=_("Span Name")),
        OptionValues.Field(id="status.code", source=OptionValues.Source.METHOD, label=_("状态")),
        OptionValues.Field(id="kind", source=OptionValues.Source.METHOD, label=_("类型")),
        OptionValues.Field(id="resource.telemetry.sdk.version", source=OptionValues.Source.ES, label=_("版本")),
        OptionValues.Field(id="resource.service.name", source=OptionValues.Source.ES, label=_("服务")),
        OptionValues.Field(id="resource.bk.instance.id", source=OptionValues.Source.ES, label=_("实例")),
    ]

    def get_kind(self):
        return SpanKind.list()

    def get_status_code(self):
        return [
            {"value": StatusCode.UNSET.value, "text": _("未设置")},
            {"value": StatusCode.OK.value, "text": _("正常")},
            {"value": StatusCode.ERROR.value, "text": _("异常")},
        ]


class QueryHandler:
    """查询语句处理"""

    def __init__(
        self,
        transformer,
        ordering,
        query_string,
    ):
        self.transformer = transformer
        self.query_string = query_string
        self.ordering = ordering

    @property
    def es_dsl(self):
        """
        扫描全量符合条件的文档
        """
        search_object = Search()
        # 添加排序
        search_object = search_object.sort(*self.ordering)

        # queryString处理
        if self.query_string:
            search_object = self.transformer.generate_query(search_object, self.query_string)

        return search_object.to_dict()

    @classmethod
    def has_field_not_in_fields_in_query(cls, query, fields, opposite):
        """判断查询语句中是否包含非标准字段"""

        tree = parser.parse(query, lexer=lexer)
        if isinstance(tree, Word):
            return False

        transformer = FieldTransformer(fields, opposite)
        transformer.visit(tree)
        return transformer.is_has_field_not_in_fields

    @classmethod
    def has_field_not_in_fields(cls, query, filters, fields, opposite=False):
        """判断query和filters中是否有key在fields里面"""
        if query:
            is_query_contain = cls.has_field_not_in_fields_in_query(query, fields, opposite)
            if is_query_contain:
                return is_query_contain

        return FieldTransformer(fields, opposite).has_file_not_in_filters(filters)

    @classmethod
    def query_option_values(cls, mode, bk_biz_id, app_name, start_time, end_time):

        if mode == QueryMode.TRACE:
            option = TraceOptionValues(bk_biz_id, app_name)
        else:
            option = SpanOptionValues(bk_biz_id, app_name)

        return OptionValues.get_option_values(option, start_time, end_time)

    @classmethod
    def get_file_option_values(cls, bk_biz_id, app_name, fields, start_time, end_time):
        # 使用预计算表查询 -> 补充前缀collections
        option = TraceOptionValues(bk_biz_id, app_name)
        fields = [f"{TraceQueryTransformer.PRE_CALC_STANDARD_FIELD_PREFIX}.{i}" for i in fields]
        response = OptionValues.get_field_option_values(option, fields, start_time, end_time)
        # 去除前缀
        res = {}
        for k, v in response.items():
            res[k.replace(f"{TraceQueryTransformer.PRE_CALC_STANDARD_FIELD_PREFIX}.", "")] = v
        return res

    @classmethod
    def handle_trace_list(cls, trace_list):
        """对API返回的Trace列表进行额外处理"""
        for i in trace_list:
            i["root_service_status_code"] = StatusCodeAttributePredicate.predicate_error(
                i.get("root_service_status_code")
            )
            i["root_service_category"] = {
                "text": CategoryEnum.get_label_by_key(i["root_service_category"]),
                "value": i["root_service_category"],
            }

    @classmethod
    def handle_span_list(cls, span_list):
        """对API返回的Span列表进行额外处理"""
        for i in span_list:
            i["status_code"] = SpanPredicate.predicate_status_code(i)
