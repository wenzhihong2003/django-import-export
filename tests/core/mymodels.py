# coding=utf-8
from __future__ import unicode_literals, absolute_import, print_function

import logging
import uuid
import json

import arrow
import requests
import tempfile

from django.dispatch import receiver
from jsonfield import JSONField

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import UserManager, PermissionsMixin
from django.core import validators
from django.core.mail import send_mail
from django.core.files import File
from django.db import models, transaction, connection
from django.utils.encoding import python_2_unicode_compatible
from django.utils import timezone

from import_export.signals import post_import, post_export

from ckeditor.fields import RichTextField
from ckeditor_uploader.fields import RichTextUploadingField
import bleach

logger = logging.getLogger('wh')

PRODUCT_COL_NAME = 'pid'  # 产品列名
USER_COL_NAME = 'uid'     # 用户列名

MY_ALLOWED_TAGS = ['a', 'abbr', 'acronym', 'b', 'blockquote', 'code', 'em', 'i', 'li', 'ol', 'strong', 'ul','img',
                   'table', 'thead', 'tbody', 'tr', 'th', 'td', 'p', 'span', ]

def allowall_filter_attributes(name, value):
    return True

MY_ALLOW_ATTRIBUTES = {tag: allowall_filter_attributes for tag in MY_ALLOWED_TAGS}

MY_ALLOWED_STYLES = [
    'azimuth', 'background-color','border-bottom-color', 'border-collapse', 'border-color',
    'border-left-color', 'border-right-color', 'border-top-color', 'clear',
    'color', 'cursor', 'direction', 'display', 'elevation', 'float', 'font',
    'font-family', 'font-size', 'font-style', 'font-variant', 'font-weight',
    'height', 'letter-spacing', 'line-height', 'overflow', 'pause',
    'pause-after', 'pause-before', 'pitch', 'pitch-range', 'richness',
    'speak', 'speak-header', 'speak-numeral', 'speak-punctuation',
    'speech-rate', 'stress', 'text-align', 'text-decoration', 'text-indent',
    'unicode-bidi', 'vertical-align', 'voice-family', 'volume',
    'white-space', 'width',
    'auto', 'aqua', 'black', 'block', 'blue',
    'bold', 'both', 'bottom', 'brown', 'center', 'collapse', 'dashed',
    'dotted', 'fuchsia', 'gray', 'green', '!important', 'italic', 'left',
    'lime', 'maroon', 'medium', 'none', 'navy', 'normal', 'nowrap', 'olive',
    'pointer', 'purple', 'red', 'right', 'solid', 'silver', 'teal', 'top',
    'transparent', 'underline', 'white', 'yellow'
]

def bleach_clean(htmltext):
    if htmltext:
        return bleach.clean(htmltext, tags=MY_ALLOWED_TAGS, attributes=MY_ALLOW_ATTRIBUTES, styles=MY_ALLOWED_STYLES,
                            strip=True, strip_comments=True)
    else:
        return ''


def uuid_hex_str():
    return uuid.uuid4().get_hex()


def userinfo_avatar_uploadto(instance, filename):
    return 'useravatar/{}/{}.{}'.format(arrow.get().format('YYYY/MM/DD'), uuid_hex_str(), filename.split('.')[::-1][0])

def avatar_from_url(url, userinfo):
    """
    把url的图片转化为用户的头像
    到微信服务器下载图片时, 在阿里云上会遇到下载很慢的问题. 所以这里就先不用下载到本地了.
    这个问题也不是时时发生, 就有时来下抽风
    :type url: str
    :type userinfo: simu.models.UserInfo
    """
    res = requests.get(url)
    if res.ok:
        content_type = res.headers['content-type']
        fileext = content_type.split('/')[1] if content_type else 'png'
        if fileext == '*':
            fileext = 'png'
        tmp_file = tempfile.NamedTemporaryFile(delete=True)
        tmp_file.write(res.content)
        userinfo.avatar.save('myavatar.' + fileext, File(tmp_file))
    else:
        logger.error('把url的图片转化为用户的头像时, 访问url={}出错'.format(url) )


@python_2_unicode_compatible
class UserInfo(AbstractBaseUser, PermissionsMixin):
    """
    用户信息

    关于 reverse relation 信息
    risk_eval  RiskEvaluationInfo 类型  风险测评信息
    wish_buy_products   BuyWish 类型   申请购买产品
    """
    username = models.CharField(
        '用户名', max_length=64, unique=True, help_text='必填。不多于64个字符。只能用字母、数字和字符 @/./+/-/_',
        validators=[
            validators.RegexValidator(r'^[\w.@+-]+$', '请输入合法用户名。只能包含字母，数字和@/./+/-/_ 字符'),
        ],
        error_messages={
            'unique': "已存在一位使用该名字的用户",
        },
    )
    email = models.EmailField('电子邮件地址', blank=True)
    is_staff = models.BooleanField('职员状态', default=False, help_text='指明用户是否可以登录到这个管理站点', )
    is_active = models.BooleanField('有效', default=True, help_text='指明用户是否被认为活跃的。以反选代替删除帐号', )
    date_joined = models.DateTimeField('加入日期', default=timezone.now)

    wechat_openid = models.CharField('微信openid', max_length=64, blank=True, db_index=True)
    nick_name = models.CharField('昵称', max_length=64, blank=True)
    avatar = models.ImageField('头像地址', upload_to=userinfo_avatar_uploadto, max_length=240, blank=True, null=True)

    real_name = models.CharField('真实姓名', max_length=32, blank=True)
    idno = models.CharField('身份证号', max_length=32, blank=True)
    ispass_byidno = models.NullBooleanField('是否通过真实身份认证', help_text='这是调用中登接口进行校验的')
    mobile = models.CharField('手机号', max_length=32, blank=True)
    sales_department = models.ForeignKey('SalesDepartment', verbose_name='所属营业部', blank=True, null=True)

    is_user_agreement = models.NullBooleanField('是否同意用户协议', blank=True)
    is_invest_promise = models.NullBooleanField('是否合格投资者承诺', blank=True)

    objects = UserManager()
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    ACTIVE_BUYER = {'is_staff': False, 'is_active': True}  # 没有删除的购买者

    class Meta:
        swappable = 'AUTH_USER_MODEL'
        db_table = 'data_user_info'
        verbose_name = '用户'
        verbose_name_plural = '用户'

    def __str__(self):
        return self.username

    @transaction.atomic
    def save(self, *args, **kwargs):
        return super(UserInfo, self).save(*args, **kwargs)

    def get_full_name(self):
        return self.real_name.strip() if self.real_name else '未知名字'

    def get_short_name(self):
        return self.get_full_name()

    def email_user(self, subject, message, from_email=None, **kwargs):
        if self.email:
            send_mail(subject, message, from_email, [self.email], **kwargs)
        else:
            logger.warn('userid={}, username={} 没有email, 不能发送email'.format(self.id, self.username) )

    @property
    def avatar_with_defalut(self):
        if self.avatar:
            if self.avatar.name.startswith('http'):
                return self.avatar.name
            else:
                return self.avatar.url
        else:
            return '/static/images/head-2.png'

    @classmethod
    def find_by_weixinopenid(cls, openid):
        qs = cls.objects.filter(wechat_openid=openid)
        return qs[0] if qs else None

    @classmethod
    def create_from_wechat(cls, wechat_userinfo):
        logger.info('从微信创建保存用户信息....' + wechat_userinfo.openid)
        u = cls()
        u.username = 'wechat_' + uuid.uuid4().get_hex()
        u.wechat_openid = wechat_userinfo.openid
        u.nick_name = wechat_userinfo.nickname
        u.avatar = wechat_userinfo.headimgurl
        u.save()
        # avatar_from_url(wechat_userinfo.headimgurl, u)
        return u


@python_2_unicode_compatible
class RiskEvaluationInfo(models.Model):
    """
    用户风险测评信息
    """
    user = models.OneToOneField(UserInfo, verbose_name='用户', db_column=USER_COL_NAME, related_name='risk_eval',
                                limit_choices_to =UserInfo.ACTIVE_BUYER)
    iscomplete = models.NullBooleanField('是否完成')
    answer = JSONField('答案', blank=True)
    score = models.IntegerField('得分', default=0)

    class Meta:
        db_table = 'data_risk_eval'
        verbose_name = '用户风险测评信息'
        verbose_name_plural = '用户风险测评信息'


    MARK_SHEET = { # 评分表, 根据客户给的 私募投资基金投资者风险调查问卷.docx 文件得出
        '1': {'A': 4, 'B': 5, 'C':3, 'D':2},
        '2': {'A': 2, 'B': 3, 'C':4, 'D':5},
        '3': {'A': 3, 'B': 4, 'C':4, 'D':5},
        '4': {'A': 3, 'B': 5, 'C':6, 'D':7, 'E':8},
        '5': {'A': 2, 'B': 3, 'C':4, 'D':5},
        '6': {'A': 4, 'B': 5, 'C':6},
        '7': {'A': 3, 'B': 5, 'C':6, 'D':7},
        '8': {'A': 3, 'B': 5, 'C':6, 'D':7, 'E':8},
        '9': {'A': 4, 'B': 6, 'C':7, 'D':8},
        '10': {'A': 3, 'B': 5, 'C':7},
        '11': {'A': 4, 'B': 6, 'C':10, 'D':12},
        '12': {'A': 4, 'B': 7, 'C':10, 'D':12},
        '13': {'A': 4, 'B': 7, 'C':10, 'D':12},
    }

    @classmethod
    def calc_score(cls, answer_json):
        """
        根据答案计算得分
        :type answer_json: dict | str
        """
        if isinstance(answer_json, (str, unicode)):
            answer_json = json.loads(answer_json)
        score = 0
        for k, v in answer_json.items():
            score += cls.MARK_SHEET.get(str(k).strip(), {}).get(str(v).strip().upper(), 0) if k is not None and v is not None else 0
        return score

    def risk_grade(self):
        """
        风险等级	保守型	谨慎型	稳健型	积极型	进取型
        分值区间	50分以下	51-60分	61-70分	71-85分	86-100分
        """
        if self.iscomplete:
            if self.score <= 50:
                return ('保守型', '低风险产品')
            if 51 <= self.score <= 60:
                return ('谨慎型', '低、较低风险产品')
            if 61 <= self.score <= 70:
                return ('稳健型', '低、较低、中等风险产品')
            if 71 <= self.score <= 85:
                return ('积极型', '低、较低、中等、较高风险产品')
            if 86 <= self.score:
                return ('进取型', '所有风险类型产品')
        else:
            return ('还未完成风险测评', '')

    def __str__(self):
        return 'user_id={} score={}'.format(self.user_id, self.score)

    def save(self, *args, **kwargs):
        self.score = RiskEvaluationInfo.calc_score(self.answer)
        return super(RiskEvaluationInfo, self).save(*args, **kwargs)


@python_2_unicode_compatible
class BuyedProduct(models.Model):
    """
    用户已买产品
    """
    idno = models.CharField('身份证号', max_length=32, db_index=True)
    product = models.ForeignKey('Product', verbose_name='基金产品', related_name='buyers')
    share = models.IntegerField('份额', blank=True, null=True)
    trade_date = models.DateField('交易日期')

    class Meta:
        db_table = 'data_buyed_product'
        verbose_name = '用户已买产品'
        verbose_name_plural = '用户已买产品'
        index_together = [
            ('idno', 'product')
        ]

    def __str__(self):
        return '{} 购买 {} 份额 {}'.format(self.idno, self.product_id, self.share)


@python_2_unicode_compatible
class BuyWish(models.Model):
    """
    用户申请购买产品
    """
    F_UNDISPOSE, F_DISPOSED = (1, 2)
    F_STAUTS = (
        (F_UNDISPOSE, '未处理'),
        (F_DISPOSED, '已处理'),
    )

    user = models.ForeignKey(UserInfo, verbose_name='用户', related_name='wish_buy_products',
                             limit_choices_to=UserInfo.ACTIVE_BUYER)
    product = models.ForeignKey('Product', verbose_name='基金产品', related_name='buywishers')
    share  = models.IntegerField('份额', blank=True, null=True)
    status = models.SmallIntegerField('状态', choices=F_STAUTS, default=F_UNDISPOSE)
    note = models.CharField('备注', max_length=512, blank=True)

    class Meta:
        db_table = 'data_buywish'
        verbose_name = '用户申请购买产品'
        verbose_name_plural = '用户申请购买产品'

    def __str__(self):
        return "user_id={} 申请购买 product_id={}".format(self.user_id, self.product_id)


def vendor_logo_uploadto(instance, filename):
    return 'vendorlogo/{}/{}.{}'.format(arrow.get().format('YYYY/MM/DD'), uuid_hex_str(), filename.split('.')[::-1][0])

@python_2_unicode_compatible
class Vendor(models.Model):
    """
    私募公司

    关于 reverse relations 信息
    products   Product类型  基金产品
    """
    F_UP, F_DOWN = (1, 2)
    F_STAUTS = (
        (F_UP, '上线'),
        (F_DOWN, '下线'),
    )

    vcode = models.CharField('证券投资基金业协会备案编号', max_length=20, primary_key=True, help_text='用于标识私募')
    logo = models.ImageField('公司logo', upload_to=vendor_logo_uploadto, max_length=240, blank=True, null=True,
                             help_text='规格为:200 * 60')
    short_name = models.CharField('简称', max_length=128, blank=True)
    full_name = models.CharField('全称', max_length=256, blank=True)
    brief_intro = RichTextUploadingField('公司简介', config_name='with_img', blank=True)
    team = RichTextUploadingField('核心团队', config_name='with_img', blank=True)
    investment_concept = RichTextField('投资体系', blank=True, config_name='simple_basic')
    investment_strategy = RichTextUploadingField('投资策略', blank=True, config_name='with_img')
    honor = RichTextUploadingField('公司荣誉', blank=True, config_name='with_img')
    status = models.SmallIntegerField('状态', choices=F_STAUTS, blank=True, null=True)

    class Meta:
        db_table = 'data_vendor'
        verbose_name = '私募公司'
        verbose_name_plural = '私募公司'

    def __str__(self):
        return '{}-{}'.format(self.short_name, self.vcode)

    def save(self, *args, **kwargs):
        self.brief_intro = bleach_clean(self.brief_intro)
        self.team = bleach_clean(self.team)
        self.investment_concept = bleach_clean(self.investment_concept)
        self.investment_strategy = bleach_clean(self.investment_strategy)
        self.honor = bleach_clean(self.honor)
        return super(Vendor, self).save(*args, **kwargs)

    def logo_withdefalut(self):
        return self.logo.url if self.logo else '/static/images/jg-logo.png'


class OnlineProductManager(models.Manager):
    def get_queryset(self):
        return super(OnlineProductManager, self).get_queryset().filter(
            status__in=[Product.F_COLLECT, Product.F_RUN]
        )


@python_2_unicode_compatible
class Product(models.Model):
    """
    基金产品

    buywishers   BuyWish类型             申请购买者
    buyers       BuyedProduct类型        已购买者
    affiches     ProductAffiche类型      产品公告
    """
    F_COLLECT, F_RUN, F_DOWN = (1, 2, 3)
    F_STAUTS = (
        (F_COLLECT, '募集'),
        (F_RUN, '运行'),
        (F_DOWN, '下线'),
    )
    PT_STOCK, PT_QUANT, PT_ADD, PT_COMBINE, PT_MACRO, PT_CONST_RETURN = (1, 2, 3, 4, 5, 6)
    PT_TYPES = (
        (PT_STOCK, '股票'),
        (PT_QUANT, '量化'),
        (PT_ADD, '定增'),
        (PT_COMBINE, '组合'),
        (PT_MACRO, '宏观'),
        (PT_CONST_RETURN, '固收'),
    )
    pcode = models.CharField('基金代码', primary_key=True, max_length=30)
    short_name = models.CharField('简称', max_length=40, blank=True)
    full_name = models.CharField('全称', max_length=128, blank=True)
    type = models.SmallIntegerField('类型', choices=PT_TYPES, null=True)
    vendor = models.ForeignKey(Vendor, verbose_name='私募公司(基金管理人)', related_name='products')
    issue = models.CharField('基金发行方', max_length=128, blank=True)
    trustee = models.CharField('基金托管人', max_length=128, blank=True)
    investor = models.CharField('投资人', max_length=128, blank=True)
    legal_counsel = models.CharField('法律顾问', max_length=128, blank=True)
    finance_counsel = models.CharField('财务顾问', max_length=128, blank=True)
    fund_purpose = models.CharField('资金用途', max_length=256, blank=True)

    establish_date = models.DateField('成立日期', null=True, blank=True)
    down_date = models.DateField('下线日期', null=True, blank=True)
    status = models.SmallIntegerField('状态', choices=F_STAUTS, blank=True, null=True)

    l_accumulate_profit_ratio = models.DecimalField('累计收益率(最新)', max_digits=12, decimal_places=4,
                                                    null=True, blank=True)
    l_annual_profit_ratio = models.DecimalField('年化收益率(最新)', max_digits=12, decimal_places=4,
                                                null=True, blank=True)
    l_net_value = models.DecimalField('净值(最新)', max_digits=12, decimal_places=4,
                                      null=True, blank=True)
    l_pdate = models.DateField('最新净值的日期', blank=True, null=True)

    attach_file = models.FileField('附件', upload_to='attach', help_text='产品文件', blank=True, null=True)


    objects = models.Manager()
    onlines_manager = OnlineProductManager()

    class Meta:
        db_table = 'data_product'
        verbose_name = '基金产品'
        verbose_name_plural = '基金产品'

    def __str__(self):
        return "{}-{}".format(self.short_name, self.pcode)

    @classmethod
    def update_last_netvalue(cls):
        """"
        根据 data_product_net_value 表更新最新的产品净值数据
        """
        sql = """
UPDATE data_product as product INNER JOIN
  (
    SELECT
      a.pid,
      a.pdate,
      a.net_value,
      a.accumulate_profit_ratio,
      a.annual_profit_ratio
    FROM data_product_net_value AS a
      INNER JOIN
      (
        SELECT
          pid,
          MAX(pdate) AS mpdate
        FROM data_product_net_value
        GROUP BY pid
      ) AS b
        ON a.pid = b.pid AND a.pdate = b.mpdate
    ) as base
  on product.pcode = base.pid

set product.l_net_value = base.net_value,
  product.l_accumulate_profit_ratio = base.accumulate_profit_ratio,
  product.l_annual_profit_ratio = base.annual_profit_ratio,
  product.l_pdate = base.pdate;
        """
        with connection.cursor() as cursor:
            cursor.execute(sql)


@python_2_unicode_compatible
class ProductAffiche(models.Model):
    """
    产品公告
    """
    product = models.ForeignKey(Product, db_column=PRODUCT_COL_NAME, related_name='affiches')
    title = models.CharField('标题', max_length=120)
    context = RichTextField('内容', config_name='simple_basic')
    declare_date = models.DateField('发布日期', default=timezone.now)

    class Meta:
        db_table = 'data_product_affiche'
        verbose_name = '产品公告'
        verbose_name_plural = '产品公告'

    def __str__(self):
        return "{}".format(self.title)

    def save(self, *args, **kwargs):
        self.context = bleach_clean(self.context)
        return super(ProductAffiche, self).save(*args, **kwargs)


@python_2_unicode_compatible
class ProductNetValue(models.Model):
    """
    产品净值明细
    """
    product = models.ForeignKey(Product, db_column=PRODUCT_COL_NAME, related_name='netvalues', verbose_name='基金产品')
    pdate = models.DateField('日期')
    net_value = models.DecimalField('净值', max_digits=12, decimal_places=4, null=True)
    accumulate_profit_ratio = models.DecimalField('累计收益率', max_digits=12, decimal_places=4, null=True)
    annual_profit_ratio = models.DecimalField('年化收益率', max_digits=12, decimal_places=4, null=True)

    class Meta:
        db_table = 'data_product_net_value'
        verbose_name = '产品净值明细'
        verbose_name_plural = '产品净值明细'
        index_together = [
            ('product', 'pdate')
        ]

    def __str__(self):
        return "pid={} pdate={}, netvalue={}".format(self.product_id, self.pdate, self.net_value)


@python_2_unicode_compatible
class Legal(models.Model):
    """
    法律法规

    analysises     LegalAnalysis类型      法律法规解读
    """
    title = models.CharField('标题', max_length=120)
    context = RichTextField('内容', config_name='simple_basic')
    declare_date = models.DateField('发布日期', default=timezone.now)

    class Meta:
        db_table = 'data_legal'
        verbose_name = '法律法规'
        verbose_name_plural = '法律法规'

    def __str__(self):
        return '{}'.format(self.title)

    def save(self, *args, **kwargs):
        self.context = bleach_clean(self.context)
        super(Legal, self).save(*args, **kwargs)


@python_2_unicode_compatible
class LegalAnalysis(models.Model):
    """
    法律法规解读
    """
    legal = models.ForeignKey(Legal, verbose_name='法律法规', related_name='analysises')
    title = models.CharField('标题', max_length=120)
    context = RichTextField('内容', config_name='simple_basic')
    declare_date = models.DateField('发布日期', default=timezone.now)

    class Meta:
        db_table = 'data_legal_analysis'
        verbose_name = '法律法规解读'
        verbose_name_plural = '法律法规解读'

    def __str__(self):
        return '{}'.format(self.title)

    def save(self, *args, **kwargs):
        self.context = bleach_clean(self.context)
        super(LegalAnalysis, self).save(*args, **kwargs)


@python_2_unicode_compatible
class IndustryDataContent(models.Model):
    """
    行业数据内容
    """
    title = models.CharField('标题', max_length=120, blank=True)
    content = RichTextUploadingField('内容', config_name='with_img', blank=True)
    declare_date = models.DateField('发布日期', default=timezone.now)
    attach_file = models.FileField('附件', upload_to='attach', help_text='源数据文件', blank=True, null=True)

    class Meta:
        db_table = 'data_industr_data_content'
        verbose_name = '行业数据内容'
        verbose_name_plural = '行业数据内容'

    def __str__(self):
        return '{}'.format(self.title)

    def save(self, *args, **kwargs):
        self.content = bleach_clean(self.content)
        return super(IndustryDataContent, self).save(*args, **kwargs)


@python_2_unicode_compatible
class SalesDepartment(models.Model):
    """
    营业部
    """
    code = models.CharField('编码', max_length=40, blank=True)
    name = models.CharField('名称', max_length=256)

    class Meta:
        db_table = 'data_sales_department'
        verbose_name = '营业部'
        verbose_name_plural = '营业部'

    def __str__(self):
        return '{}'.format(self.name)


@python_2_unicode_compatible
class StaticHtmlPage(models.Model):
    """
    静态页面
    """
    cn_name = models.CharField('中文名称', max_length=64)
    py_name = models.CharField('拼音名称', max_length=64, blank=True)
    html_file = models.FileField('静态页面', max_length=240, blank=True)

    class Meta:
        db_table = 'data_static_html'
        verbose_name = '静态页面'
        verbose_name_plural = '静态页面'

    def __str__(self):
        return '{}'.format(self.cn_name)


@python_2_unicode_compatible
class ZDProcess(models.Model):
    """
    中登处理流水
    """
    create_time = models.DateTimeField('创建时间', auto_now=True)
    file_name = models.CharField('请求子文件名', max_length=240, blank=True)
    userid = models.IntegerField('用户的id', null=True, blank=True)
    idno = models.CharField('身份证号', max_length=32, db_index=True)
    real_name = models.CharField('真实姓名', max_length=32, blank=True)
    rep_time = models.DateTimeField('响应创建时间', blank=True, null=True)
    rep_result = models.CharField('响应结果代码', max_length=6, blank=True)
    ispass_byidno = models.NullBooleanField('是否通过真实身份认证', blank=True, null=True)

    class Meta:
        db_table = 'data_zdprocess'
        verbose_name = '中登处理流水'
        verbose_name_plural = '中登处理流水'

    def __str__(self):
        return '{}'.format(self.create_time)

@python_2_unicode_compatible
class SmsProcess(models.Model):
    """
    短信处理流水
    """
    create_time = models.DateTimeField('创建时间', auto_now=True)
    userid = models.IntegerField('用户的id', null=True, blank=True)
    mobile = models.CharField('手机号', max_length=32)
    security_code = models.CharField('验证码', blank=True, max_length=10)
    send_result = models.CharField('发送结果', max_length=64, help_text='http 调用短信发送结果返回的信息', blank=True)

    class Meta:
        db_table = 'data_smsprocess'
        verbose_name = '短信处理流水'
        verbose_name_plural = '短信处理流水'

    def __str__(self):
        return 'userid={}, mobile={}'.format(self.userid, self.mobile)


@receiver(post_import, dispatch_uid='balabala')
def _post_import(model, **kwargs):
    """
    处理数据导入的后处理
    """
    if model == ProductNetValue:  # 处理ProductNetValue 数据的导入
        Product.update_last_netvalue()
