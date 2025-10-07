from django.db import models
from django.contrib.auth.models import UserManager, AbstractUser
from techstack.models import TechStack


class CustomUserManager(UserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("You have not provided a valid email")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_user(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra_fields)


class Employee(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    tech_stack = models.ManyToManyField(TechStack)
    project = models.CharField(max_length=50)

    ROLE_CHOICES = [
        ("MANAGER", "Manager"),
        ("RECRUITER", "Recruiter"),
        ("INTERVIEWER", "Interviewer"),
    ]

    role = models.CharField(max_length=30, choices=ROLE_CHOICES)

    LEVEL_CHOICES = [
        ("JUNIOR", "Junior"),
        ("MIDDLE", "Middle"),
        ("SENIOR", "Senior"),
    ]

    level = models.CharField(max_length=30, choices=LEVEL_CHOICES)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    @property
    def fullname(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return self.fullname
