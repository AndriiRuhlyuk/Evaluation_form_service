from django.apps import AppConfig


class QuestionConfig(AppConfig):
    """
    Django application configuration for the Question app.

    This class configures the Question app within the Django project,
    specifying the default auto field type and the app name.
    """

    # Specifies the type of auto-created primary key field
    default_auto_field = "django.db.models.BigAutoField"

    # The Python module path to the app
    name = "question"
