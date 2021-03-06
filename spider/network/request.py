# -*- coding: utf-8 -*-
"""
Created on 2018-07-25 11:49:08
---------
@summary: 请求结构体
---------
@author: Boris
@email:  boris_liu@foxmail.com
"""

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.exceptions import InsecureRequestWarning

import spider.setting as setting
import spider.utils.tools as tools
from spider.db.redisdb import RedisDB
from spider.network import user_agent
from spider.network.item import Item
from spider.network.proxy_pool import proxy_pool
from spider.network.response import Response
from spider.utils.log import log

# 屏蔽warning信息
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


class Request(object):
    session = None
    user_agent_pool = user_agent
    proxies_pool = proxy_pool

    cache_db = None  # redis / pika
    cached_table_folder = (
        None
    )  # 缓存response的文件文件夹 response_cached:cached_table_folder:md5
    cached_expire_time = 1200  # 缓存过期时间

    local_filepath = None
    oss_handler = None

    __REQUEST_ATTRS__ = [
        # 'method', 'url', 必须传递 不加入**kwargs中
        "params",
        "data",
        "headers",
        "cookies",
        "files",
        "auth",
        "timeout",
        "allow_redirects",
        "proxies",
        "hooks",
        "stream",
        "verify",
        "cert",
        "json",
    ]

    DEFAULT_KEY_VALUE = dict(
        url="",
        retry_times=0,
        priority=300,
        parser_name=None,
        callback=None,
        filter_repeat=True,
        auto_request=True,
        request_sync=False,
        use_session=None,
        random_user_agent=True,
        download_midware=None,
        is_abandoned=False,
    )

    def __init__(
        self,
        url="",
        retry_times=0,
        priority=300,
        parser_name=None,
        callback=None,
        filter_repeat=True,
        auto_request=True,
        request_sync=False,
        use_session=None,
        random_user_agent=True,
        download_midware=None,
        is_abandoned=False,
        **kwargs,
    ):
        """
        @summary:
        ---------
        @param url: 待抓取url
        @param retry_times: 当前重试次数
        @param priority: 优先级 越小越优先 默认300
        @param parser_name: 回调函数所在的类名 默认为当前类
        @param callback: 回调函数 可以是函数 也可是函数名（如想跨类回调时，parser_name指定那个类名，callback指定那个类想回调的方法名即可）
        --
        @param filter_repeat: 是否需要去重 (True/False) 当setting中的REQUEST_FILTER_ENABLE设置为True时该参数生效 默认True
        @param auto_request: 是否需要自动请求下载网页 默认是。设置为False时返回的response为空，需要自己去请求网页
        @param request_sync: 是否同步请求下载网页，默认异步。如果该请求url过期时间快，可设置为True，相当于yield的reqeust会立即响应，而不是去排队
        @param use_session: 是否使用session方式
        @param random_user_agent: 是否随机User-Agent (True/False) 当setting中的RANDOM_HEADERS设置为True时该参数生效 默认True
        @param download_midware: 下载中间件。默认为parser中的download_midware
        @param is_abandoned: 当发生异常时是否放弃重试 True/False. 默认False
        --
        @param method: 新建 Request 对象要使用的HTTP方法
        @param params: (可选) Request 对象的查询字符中要发送的字典或字节内容
        @param data: (可选) Request 对象的 body 中要包括的字典、字节或类文件数据
        @param json: (可选) Request 对象的 body 中要包括的 Json 数据
        @param headers: (可选) Request 对象的字典格式的 HTTP 头
        @param cookies: (可选) Request 对象的字典或 CookieJar 对象
        @param files: (可选) 字典，'name': file-like-objects (或{'name': ('filename', fileobj)}) 用于上传含多个部分的（类）文件对象
        @param auth: (可选) Auth tuple to enable Basic/Digest/Custom HTTP Auth.
        @param timeout (浮点或元组): (可选) 等待服务器数据的超时限制，是一个浮点数，或是一个(connect timeout, read timeout) 元组
        @param allow_redirects (bool): (可选) Boolean. True 表示允许跟踪 POST/PUT/DELETE 方法的重定向
        @param proxies: (可选) 字典，用于将协议映射为代理的URL
        @param verify: (可选) 为 True 时将会验证 SSL 证书，也可以提供一个 CA_BUNDLE 路径
        @param stream: (可选) 如果为 False，将会立即下载响应内容
        @param cert: (可选) 为字符串时应是 SSL 客户端证书文件的路径(.pem格式)，如果是元组，就应该是一个(‘cert’, ‘key’) 二元值对
        --
        @param **kwargs: 其他值: 如 Request(item=item) 则item可直接用reqeust.item 取出 或requests 的其他参数
        ---------
        @result:
        """

        self.url = url
        self.retry_times = retry_times
        self.priority = priority
        self.parser_name = parser_name
        self.callback = callback
        self.filter_repeat = filter_repeat
        self.auto_request = auto_request
        self.request_sync = request_sync
        self.use_session = use_session
        self.random_user_agent = random_user_agent
        self.download_midware = download_midware
        self.is_abandoned = is_abandoned

        self.requests_kwargs = {}
        for key, value in kwargs.items():
            if key in self.__class__.__REQUEST_ATTRS__:  # 取requests参数
                self.requests_kwargs[key] = value

            self.__dict__[key] = value

    def __repr__(self):
        try:
            return "<Request {}>".format(self.url)
        except:
            return "<Request {}>".format(str(self.to_dict)[:40])

    def __setattr__(self, key, value):
        """
        针对 request.xxx = xxx 的形式，更新reqeust及内部参数值
        @param key:
        @param value:
        @return:
        """
        self.__dict__[key] = value

        if key in self.__class__.__REQUEST_ATTRS__:
            self.requests_kwargs[key] = value

    def __lt__(self, other):
        return self.priority < other.priority

    @property
    def _session(self):
        use_session = (
            setting.USE_SESSION if self.use_session is None else self.use_session
        )  # self.use_session 优先级高
        if use_session and not self.__class__.session:
            self.__class__.session = requests.Session()
            http_adapter = HTTPAdapter(
                pool_connections=1000, pool_maxsize=1000
            )  # pool_connections – 缓存的 urllib3 连接池个数  pool_maxsize – 连接池中保存的最大连接数
            self.__class__.session.mount(
                "http", http_adapter
            )  # 任何使用该session会话的 HTTP 请求，只要其 URL 是以给定的前缀开头，该传输适配器就会被使用到。

        return self.__class__.session

    @property
    def to_dict(self):
        request_dict = {}

        self.callback = (
            getattr(self.callback, "__name__")
            if callable(self.callback)
            else self.callback
        )
        self.download_midware = (
            getattr(self.download_midware, "__name__")
            if callable(self.download_midware)
            else self.download_midware
        )

        for key, value in self.__dict__.items():
            if (
                key in self.__class__.DEFAULT_KEY_VALUE
                and self.__class__.DEFAULT_KEY_VALUE.get(key) == value
                or key == "requests_kwargs"
            ):
                continue

            if callable(value) or isinstance(value, Item):  # 序列化 如item
                value = tools.dumps_obj(value)

            request_dict[key] = value

        return request_dict

    def get_response(self, save_cached=False):
        """
        获取带有selector功能的response
        @param save_cached: 保存缓存 方便调试时不用每次都重新下载
        @return:
        """
        # 设置超时默认时间
        self.requests_kwargs.setdefault("timeout", 22)  # connect=22 read=22

        # 设置stream
        self.requests_kwargs.setdefault(
            "stream", True
        )  # 默认情况下，当你进行网络请求后，响应体会立即被下载。你可以通过 stream 参数覆盖这个行为，推迟下载响应体直到访问 Response.content 属性。此时仅有响应头被下载下来了。缺点： stream 设为 True，Requests 无法将连接释放回连接池，除非你 消耗了所有的数据，或者调用了 Response.close。 这样会带来连接效率低下的问题。

        # 关闭证书验证
        self.requests_kwargs.setdefault("verify", False)

        # 设置请求方法
        method = self.__dict__.get("method")
        if not method:
            if "data" in self.requests_kwargs:
                method = "POST"
            else:
                method = "GET"

        # 随机user—agent
        headers = self.requests_kwargs.get("headers", {})
        if "user-agent" not in headers and "User-Agent" not in headers:
            if self.random_user_agent and setting.RANDOM_HEADERS:
                headers.update({"User-Agent": self.__class__.user_agent_pool.get()})
                self.requests_kwargs.update(headers=headers)
        else:
            self.requests_kwargs.setdefault(
                "headers",
                {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.103 Safari/537.36"
                },
            )

        # 代理
        proxies = self.requests_kwargs.get("proxies", -1)
        if proxies == -1 and setting.PROXY_ENABLE and self.__class__.proxies_pool:
            while True:
                proxies = self.__class__.proxies_pool.get()
                if proxies:
                    break
                else:
                    log.debug("暂无可用代理 ...")
            proxies and self.requests_kwargs.update(proxies=proxies)

        log.debug(
            """
                -------------- %s.%s request for ----------------
                url  = %s
                method = %s
                body = %s
                """
            % (
                self.parser_name,
                (
                    self.callback
                    and callable(self.callback)
                    and getattr(self.callback, "__name__")
                    or self.callback
                )
                or "parser",
                self.url,
                method,
                self.requests_kwargs,
            )
        )

        # def hooks(response, *args, **kwargs):
        #     print(response.url)
        #
        # self.requests_kwargs.update(hooks={'response': hooks})

        use_session = (
            setting.USE_SESSION if self.use_session is None else self.use_session
        )  # self.use_session 优先级高

        if use_session:
            response = self._session.request(method, self.url, **self.requests_kwargs)
        else:
            response = requests.request(method, self.url, **self.requests_kwargs)

        response = Response(response)
        if save_cached:
            self.save_cached(response, expire_time=self.__class__.cached_expire_time)

        return response

    @property
    def fingerprint(self):
        """
        request唯一表识
        @return:
        """
        args = [self.__dict__.get("url", "")]
        params = self.requests_kwargs.get("params")
        datas = self.requests_kwargs.get("data")
        if params:
            args.append(str(params))

        if datas:
            args.append(str(datas))
        return tools.get_md5(*args)

    @property
    def _cache_db(self):
        if not self.__class__.cache_db:
            self.__class__.cache_db = RedisDB()  # .from_url(setting.pika_spider_1_uri)

        return self.__class__.cache_db

    @property
    def _cached_table_folder(self):
        if self.__class__.cached_table_folder:
            return f"response_cached:{self.__class__.cached_table_folder}:{self.fingerprint}"
        else:
            return f"response_cached:test:{self.fingerprint}"

    def save_cached(self, response, expire_time=1200):
        """
        使用redis保存response 用于调试 不用每回都下载
        @param response:
        @param expire_time: 过期时间
        @return:
        """

        self._cache_db.strset(
            self._cached_table_folder, response.to_dict, ex=expire_time
        )

    def get_response_from_cached(self, save_cached=True):
        """
        从缓存中获取response
        注意：
            属性值为空：
                -raw ： urllib3.response.HTTPResponse
                -connection：requests.adapters.HTTPAdapter
                -history

            属性含义改变：
                - request 由requests 改为Request
        @param: save_cached 当无缓存 直接下载 下载完是否保存缓存
        @return:
        """
        response_dict = self._cache_db.strget(self._cached_table_folder)
        if not response_dict:
            log.info("无response缓存  重新下载")
            response_obj = self.get_response(save_cached=save_cached)
        else:
            response_dict = eval(response_dict)
            response_obj = Response.from_dict(response_dict)
        return response_obj

    def del_response_cached(self):
        self._cache_db.clear(self._cached_table_folder)

    @classmethod
    def from_dict(cls, request_dict):
        for key, value in request_dict.items():
            if isinstance(value, bytes):  # 反序列化 如item
                request_dict[key] = tools.loads_obj(value)

        return cls(**request_dict)

    def copy(self):
        return self.__class__.from_dict(self.to_dict)
