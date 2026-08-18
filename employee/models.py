from django.db import models
from django.contrib.auth.models import UserManager, AbstractUser


class CustomUserManager(UserManager):
    """
    Custom user manager that extends Django's UserManager.
    Handles the creation of users and superusers with email as the unique identifier instead of username.
    """

    use_in_migrations = (
        True  # Indicates that this manager should be used during migrations
    )

    def _create_user(self, email, password, **extra_fields):
        """
        Base method for creating a user with the given email and password.

        Args:
            email: User's email address (used as username)
            password: User's password
            **extra_fields: Additional fields to be set on the user model

        Returns:
            User instance

        Raises:
            ValueError: If email is not provided
        """
        if not email:
            raise ValueError("You have not provided a valid email")

        email = self.normalize_email(email)  # Normalize the email address
        user = self.model(email=email, **extra_fields)  # Create a new user instance
        user.set_password(password)  # Set the password
        user.save(using=self._db)  # Save the user to the database

        return user

    def create_user(self, email=None, password=None, **extra_fields):
        """
        Create and save a regular user with the given email and password.

        Args:
            email: User's email address
            password: User's password
            **extra_fields: Additional fields to be set on the user model

        Returns:
            User instance
        """
        extra_fields.setdefault("is_staff", True)  # Set is_staff to True by default
        extra_fields.setdefault(
            "is_superuser", False
        )  # Set is_superuser to False by default
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email=None, password=None, **extra_fields):
        """
        Create and save a superuser with the given email and password.

        Args:
            email: User's email address
            password: User's password
            **extra_fields: Additional fields to be set on the user model

        Returns:
            User instance with superuser privileges
        """
        extra_fields.setdefault("is_staff", True)  # Set is_staff to True
        extra_fields.setdefault("is_superuser", True)  # Set is_superuser to True
        return self._create_user(email, password, **extra_fields)


class Employee(AbstractUser):
    """
    Custom user model that extends Django's AbstractUser.
    Uses email instead of username for authentication and adds role and level fields.
    """

    username = None  # Remove username field as we use email instead
    email = models.EmailField(unique=True)  # Email field, must be unique
    is_active = models.BooleanField(
        default=True
    )  # Flag indicating if the user account is active
    updated_at = models.DateTimeField(
        auto_now=True
    )  # Automatically updated when the model is saved

    # Available roles for employees in the system
    ROLE_CHOICES = [
        ("HIRING_MANAGER", "Hiring Manager"),
        ("MANAGER", "Manager"),
        ("RECRUITER", "Recruiter"),
        ("INTERVIEWER", "Interviewer"),
    ]

    role = models.CharField(
        max_length=30, choices=ROLE_CHOICES
    )  # Employee's role in the organization

    # Available experience levels for employees
    LEVEL_CHOICES = [
        ("JUNIOR", "Junior"),
        ("MIDDLE", "Middle"),
        ("SENIOR", "Senior"),
        ("LEAD", "Lead"),
        ("HEAD", "Head"),
    ]

    level = models.CharField(
        max_length=30, choices=LEVEL_CHOICES
    )  # Employee's experience level

    objects = CustomUserManager()  # Use the custom manager for this model

    USERNAME_FIELD = "email"  # Use email as the username field for authentication
    REQUIRED_FIELDS = []  # No additional required fields for creating a user

    @property
    def fullname(self):
        """
        Returns the full name of the employee by combining first and last name.

        Returns:
            str: Full name of the employee
        """
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        """
        String representation of the employee.

        Returns:
            str: Full name of the employee
        """
        return self.fullname
