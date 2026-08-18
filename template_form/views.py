from rest_framework.decorators import action
from django.db.models import Count, Q, Prefetch, prefetch_related_objects

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import viewsets, filters, status, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from template_form.models import TemplateForm, TemplateFormItems, TemplateFormTopic
from template_form.permissions import IsManagerOrSuperuser
from template_form.serializers import (
    TemplateFormListSerializer,
    TemplateFormDetailSerializer,
    TemplateFormSerializer,
    TemplateFormItemsDetailSerializer,
    TemplateFormItemsListSerializer,
    TemplateFormItemUpdateSerializer,
)
from template_form.services import (
    _synchronize_form_topics,
    clone_template_to_working,
    save_template_draft,
    publish_template_form,
)
from working_form.models import WorkingForm
from working_form.permissions import IsRecruiter
from working_form.serializers import (
    WorkingFormCreateSerializer,
    WorkingFormDetailSerializer,
)
from working_form.views import WorkingFormViewSet


class TemplateFormViewSet(viewsets.ModelViewSet):
    """
    A ViewSet for managing form templates (`TemplateForm`).

    Provides a full set of CRUD operations (Create, Read, Update, Delete) for
    form templates, as well as additional actions for draft management and
    creating working forms.

    **Key features:**
    - Full CRUD operations for templates.
    - Filtering by technology stack and topics.
    - Full-text search by template name.
    - Use of different serializers for list and detail views.
    - Draft management and publishing.
    - Cloning a template into a working form (`WorkingForm`).

    **Endpoints:**
    - `GET /api/template-form/` — Retrieve a list of active templates.
    - `POST /api/template-form/` — Create a new template.
    - `GET /api/template-form/{slug}/` — Retrieve template details.
    - `PUT /api/template-form/{slug}/` — Fully update a template.
    - `PATCH /api/template-form/{slug}/` — Partially update a template.
    - `DELETE /api/template-form/{slug}/` — Delete a template.
    - `PATCH /api/template-form/{slug}/save_draft/` — Save a draft.
    - `POST /api/template-form/{slug}/publish/` — Publish a draft.
    - `POST /api/template-form/{slug}/create_working_form/` — Create a working form.
    """

    # Base queryset with optimized database access
    # Example result: [TemplateForm(id=1, name="Java Developer Interview"), TemplateForm(id=2, name="Python Developer Interview")]
    queryset = (
        TemplateForm.objects.select_related(
            "tech_stack", "manager"
        )  # Joins tech_stack and manager tables
        .prefetch_related(
            Prefetch(
                "form_topics",  # Prefetches related topics
                queryset=TemplateFormTopic.objects.order_by(
                    "topic__name"
                )  # Orders topics by name
                .select_related("topic")  # Joins topic table
                .prefetch_related(
                    "items__origin_question"
                ),  # Prefetches items and their origin questions
            ),
        )
        .annotate(
            # Count of topics in this form
            # Example: 5 (meaning the form has 5 topics)
            topics_count=Count("form_topics", distinct=True),
            # Count of active (non-removed) items/questions in this form
            # Example: 25 (meaning the form has 25 active questions)
            active_items_count=Count(
                "form_topics__items", filter=Q(form_topics__items__is_removed=False)
            ),
        )
    )

    # Filter backends for search, filtering, and ordering
    # Used by DRF to process query parameters
    filter_backends = [
        DjangoFilterBackend,  # Enables filtering by field values
        filters.SearchFilter,  # Enables text search
        filters.OrderingFilter,  # Enables ordering by fields
    ]

    # Fields that can be filtered and how they can be filtered
    # Example query parameters:
    # - ?tech_stack=1 (filter by tech_stack id)
    # - ?tech_stack__name=Java (filter by tech_stack name containing "Java")
    # - ?topics=1 (filter by topic id)
    filterset_fields = {
        "tech_stack": ["exact"],  # Filter by exact tech_stack id
        "tech_stack__name": ["icontains"],  # Filter by tech_stack name containing text
        "topics": ["exact"],  # Filter by exact topic id
    }

    # Fields to search in when using the search parameter
    # Example: ?search=Java (searches in the name field)
    search_fields = ["name"]

    # Fields that can be used for ordering
    # Example: ?ordering=created_at or ?ordering=-created_at (descending)
    ordering_fields = ["created_at"]

    # Field to use for object lookup instead of pk
    # Example: /api/template-form/java-developer-interview/ (uses slug="java-developer-interview")
    lookup_field = "slug"

    def get_permissions(self):
        """
        Determines access permissions based on the action.

        - For safe actions (`list`, `retrieve`): `IsAuthenticated`.
        - For all other actions (create, update, delete): `IsManagerOrSuperuser`.

        Returns:
            list: List of permission classes to apply
                 Examples:
                 - [IsAuthenticated()] for list/retrieve actions
                 - [IsManagerOrSuperuser()] for create/update/delete actions
        """
        # Check if the current action is a read-only action
        # self.action - String name of the current action (e.g., "list", "retrieve", "create")
        if self.action in ["list", "retrieve"]:
            # For read-only actions, only require authentication
            # Returns a list containing a single permission class instance
            return [IsAuthenticated()]

        # For write actions, require manager or superuser permissions
        # Returns a list containing a single permission class instance
        return [IsManagerOrSuperuser()]

    def get_serializer_class(self):
        """
        Selects the serializer class based on the current action (`action`).

        - `create_working_form`: `WorkingFormCreateSerializer` for input validation.
        - `list`: `TemplateFormListSerializer` for a concise list view.
        - `retrieve`: `TemplateFormDetailSerializer` for a full representation.
        - Others (`create`, `update`): `TemplateFormSerializer` for write operations.

        Returns:
            class: The serializer class to use for the current action
                  Examples:
                  - WorkingFormCreateSerializer for "create_working_form" action
                  - TemplateFormListSerializer for "list" action
                  - TemplateFormDetailSerializer for "retrieve" action
                  - TemplateFormSerializer for other actions
        """
        # For creating working forms, use the working form serializer
        # Example: When POST to /api/template-form/{slug}/create_working_form/
        if self.action == "create_working_form":
            return WorkingFormCreateSerializer

        # For listing templates, use the list serializer
        # Example: When GET to /api/template-form/
        if self.action == "list":
            return TemplateFormListSerializer

        # For retrieving a single template, use the detail serializer
        # Example: When GET to /api/template-form/{slug}/
        elif self.action == "retrieve":
            return TemplateFormDetailSerializer

        # For all other actions (create, update), use the main serializer
        # Example: When POST to /api/template-form/ or PUT to /api/template-form/{slug}/
        return TemplateFormSerializer

    def get_serializer_context(self):
        """
        Adds the request object (`request`) to the serializer context.

        This allows the serializer to access the current user, for example,
        to set the `manager` field when creating a form.

        Returns:
            dict: Dictionary containing context data for the serializer
                 Example: {"request": <Request: GET '/api/template-form/'>}
        """
        # Return a dictionary with the request object
        # self.request - The current HTTP request object
        # Example: {"request": <Request: GET '/api/template-form/'>}
        return {"request": self.request}

    @extend_schema(
        summary="save draft template form",
        description="""Save current forms state as JSON in `draft_data` field
        without modifying the core template data. This endpoint is intended for autosave.""",
        request=serializers.Serializer,
        responses={200: {"description": "Draft saved successfully."}},
        tags=["Template Form"],
    )
    @action(
        detail=True,
        methods=["patch"],
        permission_classes=[IsAuthenticated, IsManagerOrSuperuser],
    )
    def save_draft(self, request, slug=None):
        """
        PATCH /api/template-form/{slug}/save-draft/
        Saves the request data as a draft for later use.

        Sets `has_unpublished_changes=True` and updates `draft_updated_at`.
        Does not validate the data; it is stored "as is".

        Args:
            request (Request): The HTTP request object containing the draft data
                              Example: Request with data={"name": "Updated Java Interview", "topics_with_questions": [...]}
            slug (str): The slug of the template form to save draft for
                       Example: "java-developer-interview"

        Returns:
            Response: HTTP response with status and timestamp
                     Example: {"status": "draft saved", "draft_updated_at": "2023-05-15T14:30:45Z"}
        """
        # Get the template form instance by slug
        # Example: TemplateForm(id=1, name="Java Developer Interview", slug="java-developer-interview")
        instance = self.get_object()

        # Call service function to save the draft data
        # instance - The template form instance to update
        # request.data - The data to save as draft (Example: {"name": "Updated Java Interview", ...})
        save_template_draft(instance, request.data)

        # Return success response with updated timestamp
        # Example: {"status": "draft saved", "draft_updated_at": "2023-05-15T14:30:45Z"}
        return Response(
            {
                "status": "draft saved",
                "draft_updated_at": instance.draft_updated_at,
            }
        )

    @extend_schema(
        summary="Publish draft",
        description="""Applies changes from the `draft_data` field to the main template.
        Before publishing, the draft data is validated. Upon success, the draft
        is cleared.""",
        request=None,
        responses={
            200: {"description": "Template saved successfully."},
            400: {"description": "No changes to publish or validation error occurred."},
        },
        tags=["Template Form"],
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsManagerOrSuperuser],
    )
    def publish(self, request, slug=None):
        """
        POST /api/template-form/{slug}/publish/
        Publishes the saved draft by applying its changes to the template.

        Calls the `publish_template_form` service function, which validates
        the data from `draft_data` and updates the main form instance.

        Args:
            request (Request): The HTTP request object
                              Example: Request with empty data (body not used)
            slug (str): The slug of the template form to publish draft for
                       Example: "java-developer-interview"

        Returns:
            Response: HTTP response with status
                     Example success: {"status": "Published successfully"}
                     Example error: {"error": "No changes to publish"} or {"error": "Validation error message"}
        """
        # Get the template form instance by slug
        # Example: TemplateForm(id=1, name="Java Developer Interview", slug="java-developer-interview")
        instance = self.get_object()

        # Check if there are any unpublished changes to publish
        # instance.has_unpublished_changes - Boolean flag (Example: True)
        if not instance.has_unpublished_changes:
            # Return error response if no changes to publish
            # Example: {"error": "No changes to publish"}
            return Response(
                {"error": "No changes to publish"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Call service function to publish the draft
            # instance - The template form instance to update
            # request.user - The user making the request (Example: User(id=1, username="manager1"))
            publish_template_form(instance, request.user)

            # Return success response
            # Example: {"status": "Published successfully"}
            return Response(
                {"status": "Published successfully"}, status=status.HTTP_200_OK
            )
        except Exception as e:
            # Return error response if validation fails
            # Example: {"error": "Invalid data in draft: field 'name' is required"}
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Create a working form from a template",
        description="""Creates a deep copy of the template as a new working form (`WorkingForm`),
        assigning additional attributes such as vacancy, level, and interviewers.""",
        request=WorkingFormCreateSerializer,
        responses={201: WorkingFormDetailSerializer},
        tags=["Form Templates", "Working Forms"],
    )
    @action(
        detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsRecruiter]
    )
    def create_working_form(self, request, slug=None):
        """
        Creates a `WorkingForm` instance based on the current template.

        Validates the input data using `WorkingFormCreateSerializer`, clones the
        template via the `clone_template_to_working` service, and returns the
        serialized instance of the new working form.

        Args:
            request (Request): The HTTP request object containing working form data
                              Example: Request with data={
                                "vacancy": 1,
                                "level": "MIDDLE",
                                "interviewers": [1, 2],
                                "recruiters": [3],
                                "approvers": [4, 5]
                              }
            slug (str): The slug of the template form to use as base
                       Example: "java-developer-interview"

        Returns:
            Response: HTTP response with the created working form data
                     Example success: WorkingFormDetailSerializer data with status 201
                     Example error: {"error": "Validation error message"} with status 400
        """
        # Get the template form instance by slug
        # Example: TemplateForm(id=1, name="Java Developer Interview", slug="java-developer-interview")
        template_form = self.get_object()

        # Prepare serializer context with request
        # Example: {"request": <Request: POST '/api/template-form/java-developer-interview/create_working_form/'>}
        context = self.get_serializer_context()
        context["request"] = request

        # Validate input data using WorkingFormCreateSerializer
        # Example input data: {"vacancy": 1, "level": "MIDDLE", "interviewers": [1, 2], ...}
        input_serializer = self.get_serializer(data=request.data, context=context)
        input_serializer.is_valid(raise_exception=True)

        try:
            # Clone the template to create a working form
            # template_form - The source template (Example: TemplateForm(id=1, name="Java Developer Interview"))
            # validated_data - The validated input data (Example: {"vacancy": 1, "level": "MIDDLE", ...})
            working_form = clone_template_to_working(
                template_form=template_form,
                validated_data=input_serializer.validated_data,
            )
        except serializers.ValidationError as e:
            # Return error if validation fails
            # Example: {"error": "Vacancy with id=1 does not exist"}
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Optimize database queries for the created working form
            # working_form_pk - Integer primary key of the created form (Example: 42)
            working_form_pk = working_form.pk

            # Create an optimized queryset with all needed relations
            # Example result: WorkingForm with all related objects prefetched
            retrieve_queryset = WorkingForm.objects.select_related(
                "tech_stack", "hiring_manager"
            ).prefetch_related("interviewers", "approvers", "approved_by", "recruiters")

            # Get the optimized working form instance
            # Example: WorkingForm(id=42, name="Java Developer Interview for Vacancy X")
            optimized_working_form = retrieve_queryset.get(pk=working_form_pk)

            # Create a temporary viewset instance to access its methods
            working_viewset_instance = WorkingFormViewSet()

            # Prefetch form topics and related data
            prefetch_related_objects(
                [optimized_working_form],
                working_viewset_instance._get_form_topics_prefetch(),
            )

        except WorkingForm.DoesNotExist:
            # Return error if the created form can't be found (should never happen)
            # Example: {"error": "Failed to reload created form"}
            return Response(
                {"error": "Failed to reload created form"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Serialize the optimized working form for response
        # Example result: Serialized WorkingForm with all related data
        output_serializer = WorkingFormDetailSerializer(
            optimized_working_form, context={"request": request}
        )

        # Return the serialized data with 201 Created status
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="List of template forms",
        description="Get list of template forms with comprehensive filtering, search and ordering options",
        parameters=[
            OpenApiParameter(
                name="search",
                type=str,
                description="Search by template forms name (ex. ?search=Java Engineer)",
            ),
            OpenApiParameter(
                name="tech_stack",
                type=str,
                description="Filter by technical stack (ex. ?tech_stack=1)",
            ),
            OpenApiParameter(
                name="tech_stack__name",
                type=str,
                description="Filter by technical stack name icontaints (ex. ?source=Jav)",
            ),
            OpenApiParameter(
                name="topics",
                type=str,
                description="Filter by topic (ex. ?topics=1)",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                description="Order by: created_at,-created_at",
            ),
        ],
        tags=["Template Form"],
    )
    def list(self, request, *args, **kwargs):
        """
        Handles the request to get a list of template forms.

        Supports filtering, searching, and ordering through query parameters.
        Uses TemplateFormListSerializer for the response.

        Args:
            request (Request): The HTTP request object with optional query parameters
                              Examples:
                              - GET /api/template-form/
                              - GET /api/template-form/?search=Java
                              - GET /api/template-form/?tech_stack=1&ordering=-created_at

        Returns:
            Response: HTTP response with list of template forms
                     Example: [
                       {
                         "id": 1,
                         "name": "Java Developer Interview",
                         "tech_stack": "Java",
                         "topics_count": 5,
                         "items_count": 25,
                         "form_detail_url": "http://example.com/api/template-form/java-developer-interview/"
                       },
                       ...
                     ]
        """
        # Call the parent class's list method to handle the request
        # Returns a Response object with serialized template forms
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Create new template form",
        tags=["Template Form"],
    )
    def create(self, request, *args, **kwargs):
        """
        Handles the request to create a new template.

        Uses TemplateFormSerializer for validation and creation.

        Args:
            request (Request): The HTTP request object with template form data
                              Example: {
                                "name": "Java Developer Interview",
                                "tech_stack": "Java",
                                "topics_with_questions": [
                                  {
                                    "topic": {"name": "ORM"},
                                    "questions": [
                                      {"question_text": "What is an ORM?", "difficulty": 1}
                                    ]
                                  }
                                ]
                              }

        Returns:
            Response: HTTP response with created template form data
                     Example: {
                       "id": 1,
                       "name": "Java Developer Interview",
                       "tech_stack": "Java",
                       "topics_with_questions": [...]
                     }
        """
        # Call the parent class's create method to handle the request
        # The serializer.create method will call create_template_form service
        # Returns a Response object with the created template form
        return super().create(request, *args, **kwargs)

    @extend_schema(
        summary="Get form template details",
        tags=["Template Form"],
    )
    def retrieve(self, request, *args, **kwargs):
        """
        Handles the request to get template form by its `slug`.

        Uses TemplateFormDetailSerializer for the response.

        Args:
            request (Request): The HTTP request object
                              Example: GET /api/template-form/java-developer-interview/

        Returns:
            Response: HTTP response with detailed template form data
                     Example: {
                       "id": 1,
                       "name": "Java Developer Interview",
                       "manager": "john.doe@example.com",
                       "tech_stack": "Java",
                       "topics_with_questions": [...],
                       "created_at": "2023-05-10T09:15:30Z",
                       "draft_data": null,
                       "has_unpublished_changes": false,
                       "draft_updated_at": null
                     }
        """
        # Call the parent class's retrieve method to handle the request
        # Returns a Response object with the detailed template form
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Full update template form",
        tags=["Template Form"],
    )
    def update(self, request, *args, **kwargs):
        """
        Handles the request to full update template (PUT method).

        Uses TemplateFormSerializer for validation and update.
        All fields must be provided.

        Args:
            request (Request): The HTTP request object with complete template form data
                              Example: {
                                "name": "Updated Java Developer Interview",
                                "tech_stack": "Java",
                                "topics_with_questions": [...]
                              }

        Returns:
            Response: HTTP response with updated template form data
                     Example: {
                       "id": 1,
                       "name": "Updated Java Developer Interview",
                       "tech_stack": "Java",
                       "topics_with_questions": [...]
                     }
        """
        # Call the parent class's update method to handle the request
        # The serializer.update method will call update_template_form service
        # Returns a Response object with the updated template form
        return super().update(request, *args, **kwargs)

    @extend_schema(
        summary="Partial update template form",
        tags=["Template Form"],
    )
    def partial_update(self, request, *args, **kwargs):
        """
        Handles the request to partial update template (PATCH method).

        Uses TemplateFormSerializer for validation and update.
        Only provided fields will be updated.

        Args:
            request (Request): The HTTP request object with partial template form data
                              Example: {"name": "Updated Java Developer Interview"}

        Returns:
            Response: HTTP response with updated template form data
                     Example: {
                       "id": 1,
                       "name": "Updated Java Developer Interview",
                       "tech_stack": "Java",
                       "topics_with_questions": [...]
                     }
        """
        # Call the parent class's partial_update method to handle the request
        # The serializer.update method will call update_template_form service
        # Returns a Response object with the updated template form
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(
        summary="Delete template form",
        tags=["Template Form"],
    )
    def destroy(self, request, *args, **kwargs):
        """
        Handles the request to delete template.

        Args:
            request (Request): The HTTP request object
                              Example: DELETE /api/template-form/java-developer-interview/

        Returns:
            Response: Empty HTTP response with 204 No Content status
        """
        # Call the parent class's destroy method to handle the request
        # Returns a Response object with 204 No Content status
        return super().destroy(request, *args, **kwargs)

    def perform_destroy(self, instance):
        """
        Soft-deletes the template instead of removing the database row.

        Working forms already cloned from this template are unaffected
        (they are copies, not references); the template just stops being
        available for new clones. Restoring is admin-only (django admin).
        """
        instance.soft_delete(self.request.user)


class TemplateFormItemViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing the item element inside TemplateForm

    **Features: **
    - Full CRUD operations
    - Search by TemplateFormItem text snapshot
    - Filter by name of topic_snapshot, topic_snapshot, source_snapshot, and is_removed
    - Different serializers for list & detail views

    **Endpoints: **
    - `GET /api/template-form/{slug}/items/` - List active TemplateFormItems
    - `GET /api/template-form/{slug}/items/{item_pk}/`` - Get TemplateFormItems details
    - `PUT /api/template-form/{slug}/items/{item_pk}/`` - Update TemplateFormItems completely
    - `PATCH /api/template-form/{slug}/items/{item_pk}/`` - Update TemplateFormItems partially
    - `DELETE /api/template-form/{slug}/items/{item_pk}/` - Soft delete TemplateFormItems instance
    """

    # Base queryset with optimized database access
    # Example result: [TemplateFormItems(id=42, text_snapshot="What is dependency injection?"), ...]
    queryset = TemplateFormItems.objects.select_related(
        "form_topic__form",  # Join to access the parent form
        "form_topic__topic",  # Join to access the topic
        "origin_question",  # Join to access the original question
        "added_by",  # Join to access the user who added this item
    )

    # Filter backends for search, filtering, and ordering
    # Used by DRF to process query parameters
    filter_backends = [
        DjangoFilterBackend,  # Enables filtering by field values
        filters.SearchFilter,  # Enables text search
        filters.OrderingFilter,  # Enables ordering by fields
    ]

    # Fields that can be filtered and how they can be filtered
    # Example query parameters:
    # - ?is_removed=false (filter by active status)
    # - ?source_snapshot=TEMPLATE (filter by source)
    # - ?topic_snapshot=ORM (filter by topic)
    filterset_fields = {
        "is_removed": ["exact"],  # Filter by removal status (true/false)
        "source_snapshot": ["exact"],  # Filter by exact source snapshot
        "topic_snapshot": ["exact"],  # Filter by exact topic snapshot
    }

    # Fields to search in when using the search parameter
    # Example: ?search=dependency (searches in text_snapshot and origin_question__question_text)
    search_fields = ["text_snapshot", "origin_question__question_text"]

    # Fields that can be used for ordering
    # Example: ?ordering=difficulty_snapshot or ?ordering=-created_at (descending)
    ordering_fields = [
        "difficulty_snapshot",  # Order by difficulty level
        "created_at",  # Order by creation date
    ]

    # Default serializer class for this viewset
    # Used when no specific serializer is selected in get_serializer_class
    serializer_class = TemplateFormItemsListSerializer

    def get_permissions(self):
        """
        Defines access permissions: `IsAuthenticated` for read operations,
        and `IsManagerOrSuperuser` for all other actions.

        Returns:
            list: List of permission classes to apply
                 Examples:
                 - [IsAuthenticated()] for list/retrieve actions
                 - [IsManagerOrSuperuser()] for create/update/delete actions
        """
        # Check if the current action is a read-only action
        # self.action - String name of the current action (e.g., "list", "retrieve", "create")
        if self.action in ["list", "retrieve"]:
            # For read-only actions, only require authentication
            # Returns a list containing a single permission class instance
            return [IsAuthenticated()]

        # For write actions, require manager or superuser permissions
        # Returns a list containing a single permission class instance
        return [IsManagerOrSuperuser()]

    def get_queryset(self):
        """
        Queryset elements filtered by TemplateForm by URL (`slug`)

        Filters the base queryset to only include items belonging to the
        template form specified in the URL.

        Returns:
            QuerySet: Filtered queryset of TemplateFormItems
                     Example: [TemplateFormItems(id=42, text_snapshot="What is dependency injection?"), ...]
        """
        # Get the base queryset from the parent class
        # Example: QuerySet of all TemplateFormItems
        base_queryset = super().get_queryset()

        # Filter the queryset to only include items from the specified form
        # self.kwargs["form_topic__form_slug"] - The slug from the URL (Example: "java-developer-interview")
        # Returns a filtered QuerySet
        return base_queryset.filter(
            form_topic__form__slug=self.kwargs["form_topic__form_slug"]
        )

    def get_serializer_class(self):
        """
        Selects the serializer: `TemplateFormItemUpdateSerializer` for updates,
        otherwise `TemplateFormItemsDetailSerializer`.

        Returns:
            class: The serializer class to use for the current action
                  Examples:
                  - TemplateFormItemUpdateSerializer for update/partial_update actions
                  - TemplateFormItemsDetailSerializer for other actions
        """
        # For update actions, use the update serializer
        # Example: When PUT or PATCH to /api/template-form/{slug}/items/{item_pk}/
        if self.action in ["update", "partial_update"]:
            return TemplateFormItemUpdateSerializer

        # For all other actions, use the detail serializer
        # Example: When GET to /api/template-form/{slug}/items/{item_pk}/
        return TemplateFormItemsDetailSerializer

    def perform_update(self, serializer):
        """
        After updating the item, synchronizes the list of topics in the parent form.

        This ensures that if a topic_snapshot was changed, the parent form's
        topics are updated accordingly.

        Args:
            serializer (TemplateFormItemUpdateSerializer): The serializer with validated data
                                                          Example: TemplateFormItemUpdateSerializer with
                                                                  data={"text_snapshot": "Updated question text"}
        """
        # Save the updated instance
        # Example: TemplateFormItems(id=42, text_snapshot="Updated question text")
        instance = serializer.save()

        # Synchronize the topics in the parent form
        # instance.form_topic.form - The parent TemplateForm instance
        _synchronize_form_topics(instance.form_topic.form)

    def perform_destroy(self, instance):
        """
        Soft-delete: flag `is_removed = True`

        Instead of actually deleting the item from the database,
        this marks it as removed by setting the is_removed flag.

        Args:
            instance (TemplateFormItems): The item to soft-delete
                                         Example: TemplateFormItems(id=42, text_snapshot="What is dependency injection?")
        """
        # Set the is_removed flag to True
        # Example: instance.is_removed changes from False to True
        instance.is_removed = True

        # Save the updated instance
        instance.save()

    @extend_schema(
        summary="List of template forms items",
        description="Get list of template form items with comprehensive filtering, search and ordering options",
        parameters=[
            OpenApiParameter(
                name="search",
                type=str,
                description="Search by snapshot text question (ex. ?text_snapshot=What is the dependency injection?)",
            ),
            OpenApiParameter(
                name="search",
                type=str,
                description="Search by origin question text question (ex. ?origin_question__question_text=What is)",
            ),
            OpenApiParameter(
                name="topic_snapshot",
                type=str,
                description="Filter by topic snapshot (ex. ?topic_snapshot=ORM)",
            ),
            OpenApiParameter(
                name="source_snapshot",
                type=str,
                description="Filter by source of question snapshot (ex. ?source=TEMPLATE)",
            ),
            OpenApiParameter(
                name="is_removed",
                type=bool,
                description="Filter by active status (ex. ?is_removed=false)",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                description="Order by: created_at, -created_at, difficulty_snapshot, -difficulty_snapshot",
            ),
        ],
        tags=["Template Form Items"],
    )
    def list(self, request, *args, **kwargs):
        """
        Handles the request to get list of form items.

        Supports filtering, searching, and ordering through query parameters.
        Uses TemplateFormItemsListSerializer for the response.

        Args:
            request (Request): The HTTP request object with optional query parameters
                              Examples:
                              - GET /api/template-form/java-developer-interview/items/
                              - GET /api/template-form/java-developer-interview/items/?search=dependency
                              - GET /api/template-form/java-developer-interview/items/?topic_snapshot=ORM

        Returns:
            Response: HTTP response with list of template form items
                     Example: [
                       {
                         "id": 42,
                         "text_snapshot": "What is dependency injection?",
                         "difficulty_snapshot": 2,
                         "item_detail_url": "http://example.com/api/template-form/java-developer-interview/items/42/"
                       },
                       ...
                     ]
        """
        # Call the parent class's list method to handle the request
        # Returns a Response object with serialized template form items
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Get form item details", tags=["Template Form Items"])
    def retrieve(self, request, *args, **kwargs):
        """
        Handles the request to get item detail.

        Uses TemplateFormItemsDetailSerializer for the response.

        Args:
            request (Request): The HTTP request object
                              Example: GET /api/template-form/java-developer-interview/items/42/

        Returns:
            Response: HTTP response with detailed form item data
                     Example: {
                       "id": 42,
                       "text_snapshot": "What is dependency injection?",
                       "difficulty_snapshot": 2,
                       "topic_snapshot": "ORM",
                       "max_score_snapshot": 5,
                       "origin_question": "What is dependency injection?",
                       "is_removed": false
                     }
        """
        # Call the parent class's retrieve method to handle the request
        # Returns a Response object with the detailed form item
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(summary="Update form items", tags=["Template Form Items"])
    def update(self, request, *args, **kwargs):
        """
        Handles the request to full update item.

        Uses TemplateFormItemUpdateSerializer for validation and update.
        All fields must be provided.

        Args:
            request (Request): The HTTP request object with complete form item data
                              Example: {
                                "text_snapshot": "Updated question text",
                                "difficulty_snapshot": 2,
                                "topic_snapshot": "ORM"
                              }

        Returns:
            Response: HTTP response with updated form item data
                     Example: {
                       "id": 42,
                       "text_snapshot": "Updated question text",
                       "difficulty_snapshot": 2,
                       "topic_snapshot": "ORM",
                       "max_score_snapshot": 5,
                       "origin_question": "What is dependency injection?",
                       "is_removed": false
                     }
        """
        # Call the parent class's update method to handle the request
        # The perform_update method will be called after successful validation
        # Returns a Response object with the updated form item
        return super().update(request, *args, **kwargs)

    @extend_schema(summary="Partial update form element", tags=["Template Form Items"])
    def partial_update(self, request, *args, **kwargs):
        """
        Handles the request to partial update item.

        Uses TemplateFormItemUpdateSerializer for validation and update.
        Only provided fields will be updated.

        Args:
            request (Request): The HTTP request object with partial form item data
                              Example: {"text_snapshot": "Updated question text"}

        Returns:
            Response: HTTP response with updated form item data
                     Example: {
                       "id": 42,
                       "text_snapshot": "Updated question text",
                       "difficulty_snapshot": 2,
                       "topic_snapshot": "ORM",
                       "max_score_snapshot": 5,
                       "origin_question": "What is dependency injection?",
                       "is_removed": false
                     }
        """
        # Call the parent class's partial_update method to handle the request
        # The perform_update method will be called after successful validation
        # Returns a Response object with the updated form item
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(
        summary="Soft delete form element ",
        description="Mark the item as deleted, without deleting from DB.",
        tags=["Template Form Items"],
    )
    def destroy(self, request, *args, **kwargs):
        """
        Handles the request to item soft delete.

        Instead of actually deleting the item from the database,
        this marks it as removed by setting the is_removed flag.

        Args:
            request (Request): The HTTP request object
                              Example: DELETE /api/template-form/java-developer-interview/items/42/

        Returns:
            Response: Empty HTTP response with 204 No Content status
        """
        # Call the parent class's destroy method to handle the request
        # The perform_destroy method will be called, which sets is_removed=True
        # Returns a Response object with 204 No Content status
        return super().destroy(request, *args, **kwargs)
