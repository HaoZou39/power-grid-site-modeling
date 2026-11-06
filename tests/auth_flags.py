from contextvars import ContextVar

skip_auto_login: ContextVar[bool] = ContextVar("skip_auto_login", default=False)
