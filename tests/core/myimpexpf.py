# coding=utf-8
""""
这里记录 wenzhihong 对 import / export 的一些工作上的探索, 免得时间长了, 好不容易得来的经验就忘记了
"""
from __future__ import (unicode_literals, absolute_import, print_function)

from datetime import datetime, date, timedelta
import tablib
from tablib.compat import xlrd
from import_export import resources, fields, widgets
from import_export.formats import base_formats
from django.core.exceptions import ObjectDoesNotExist
from django.utils.six import moves

from . import mymodels as models

class ProductXLS(base_formats.XLS):
    """
    这个自定义格式以后在用
    指定导入的数据从第几行开始, 而不是默认的第1行开始
    """
    def create_dataset(self, in_stream):
        """
        Create dataset from first sheet.
        """
        xls_book = xlrd.open_workbook(file_contents=in_stream)
        dataset = tablib.Dataset()
        sheet = xls_book.sheets()[0]

        dataset.headers = sheet.row_values(1)  # 第2行是head
        for i in moves.range(2, sheet.nrows):  # 数据从第三行开始
            dataset.append(sheet.row_values(i))
        return dataset


class ForeignKeyWidgetSkipError(widgets.ForeignKeyWidget):
    """
    外键, 忽略没有外键对应的主键没有建立起来的情况.
    这个在导入不严格的数据时比较有用, 因为往往导入的数据会有对不上的数据
    """
    def __init__(self, model, field='pk', *args, **kwargs):
        super(ForeignKeyWidgetSkipError, self).__init__(model, field, *args, **kwargs)

    def clean(self, value, row=None, *args, **kwargs):
        self.skiprow = False
        try:
            v = super(ForeignKeyWidgetSkipError, self).clean(value, row, *args, **kwargs)
        except ObjectDoesNotExist:
            v = None
            self.skiprow = True   # 这里进行标记说是要跳过行
        return v


class DateWidget1899(widgets.DateWidget):
    """
    这里是因为xls存日期是以 1899-12-25 为起始日期,到现在的天数
    这个是处理xls的日期的.
    """
    def __init__(self, format=None):
        super(DateWidget1899, self).__init__(format)

    def clean(self, value, row=None, *args, **kwargs):
        if not value:
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, (int, float)):
            return date(year=1899, month=12, day=25) + timedelta(days=value)
        for format in self.formats:
            try:
                return datetime.strptime(value, format).date()
            except (ValueError, TypeError):
                continue
        raise ValueError("Enter a valid date.")


class SkiprowModelResouce(resources.ModelResource):
    """
    如果field有标记为 skiprow, 则跳过
    """
    def skip_row(self, instance, original):
        for field in self.get_fields():
            if hasattr(field.widget, 'skiprow') and getattr(field.widget, 'skiprow'):  # 如果有标记为跳过row
                return True

        if not self._meta.skip_unchanged:
            return False
        for field in self.get_fields():
            if hasattr(field.widget, 'skiprow') and getattr(field.widget, 'skiprow'):  # 如果有标记为跳过row
                return True
            try:
                # For fields that are models.fields.related.ManyRelatedManager
                # we need to compare the results
                if list(field.get_value(instance).all()) != list(field.get_value(original).all()):
                    return False
            except AttributeError:
                if field.get_value(instance) != field.get_value(original):
                    return False
        return True


class ProductResource(SkiprowModelResouce):
    vendor = fields.Field(column_name='vendor', attribute='vendor',
                          widget=ForeignKeyWidgetSkipError(model=models.Vendor))
    establish_date = fields.Field(column_name='establish_date', attribute='establish_date', widget=DateWidget1899())

    class Meta:
        model = models.Product
        skip_unchanged = True
        fields = ('pcode', 'short_name', 'full_name', 'issue', 'trustee', 'investor', 'legal_counsel',
                  'finance_counsel', 'fund_purpose', 'establish_date', 'vendor', 'type', 'status')
        import_id_fields = ('pcode',)
        # widgets = {
        #     'establish_date': {'format': '%Y-%m-%d'},
        # }


class BuyedProductResource(SkiprowModelResouce):
    product = fields.Field(column_name='product', attribute='product',
                           widget=ForeignKeyWidgetSkipError(model=models.Product))
    trade_date = fields.Field(column_name='trade_date', attribute='trade_date', widget=DateWidget1899())
    class Meta:
        model = models.BuyedProduct
        skip_unchanged = True
        fields = ('idno', 'product', 'share', 'trade_date')
        import_id_fields = ('idno', 'product')
        # widgets = {
        #     'trade_date': {'format': '%Y-%m-%d'},
        # }


class ProductNetValueResource(SkiprowModelResouce):
    product = fields.Field(column_name='product', attribute='product',
                           widget=ForeignKeyWidgetSkipError(model=models.Product))
    pdate = fields.Field(column_name='pdate', attribute='pdate', widget=DateWidget1899())

    class Meta:
        model = models.ProductNetValue
        skip_unchanged = True
        fields = ('product', 'pdate', 'net_value', 'accumulate_profit_ratio', 'annual_profit_ratio')
        import_id_fields = ('product', 'pdate')   # 指定复合字段做为id
        # widgets = {
        #     'pdate': {'format': '%Y-%m-%d'},
        # }



class VendorResource(SkiprowModelResouce):
    class Meta:
        model = models.Vendor
        skip_unchanged = True
        fields = ('vcode', 'short_name', 'full_name', 'status')
        import_id_fields = ('vcode',)          # 指定的业务字段做为id


class SalesDepartmentResource(SkiprowModelResouce):
    class Meta:
        model = models.SalesDepartment
        fields = ('id', 'name',)
        import_id_fields = ('id',)
