import jwt
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from employee.models import Employee
from urllib.parse import parse_qs


@database_sync_to_async
def get_user(user_id):
    """
    Take user from DB
    """
    try:
        return Employee.objects.get(id=user_id)
    except Employee.DoesNotExist:
        return AnonymousUser()


class JwtAuthMiddleware(BaseMiddleware):
    """
    Custom middleware for Channels, which authenticate
    the user by JWT-token from query-param 'token'.
    """

    async def __call__(self, scope, receive, send):
        """
        Take query string, parce it, validate token (if no token - return AnonymousUser)
        put taken user in 'scope' and continue connection
        """
        query_string = scope.get("query_string", b"").decode("utf-8")

        query_params = parse_qs(query_string)
        token = query_params.get("token", [None])[0]

        if token is None:
            scope["user"] = AnonymousUser()
            return await super().__call__(scope, receive, send)

        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = payload["user_id"]

            if user_id:
                scope["user"] = await get_user(user_id)
            else:
                scope["user"] = AnonymousUser()

        except (jwt.ExpiredSignatureError, jwt.DecodeError):
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)
