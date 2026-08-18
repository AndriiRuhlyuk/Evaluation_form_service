def prefetch_count(instance, attribute_name: str) -> int:
    """
    Return count for Many-to-Many or reverse relation, using prefetch cache
    if available, otherwise falling back to SQL COUNT query.

    This function optimizes counting related objects by checking if the relation
    has been prefetched already, avoiding unnecessary database queries.

    Args:
        instance: The model instance containing the relation to count
        attribute_name: The name of the relation attribute to count

    Returns:
        int: The count of related objects
    """
    # Get the manager for the specified relation
    manager = getattr(instance, attribute_name)
    # Check if there's a prefetch cache available for this instance
    cache = getattr(instance, "_prefetched_objects_cache", None)
    # If the relation is in the prefetch cache, count objects in memory
    if cache is not None and attribute_name in cache:
        return len(manager.all())
    # Otherwise, execute a database COUNT query
    return manager.count()


class EffectiveDeletionMixin:
    """
    A mixin that implements democratic deletion logic for form elements.

    This mixin provides functionality to determine if an item should be considered
    effectively deleted based on a voting mechanism where more than half of the
    approvers must vote for deletion.

    Classes using this mixin must implement the _get_working_form method to provide
    access to the parent WorkingForm instance.
    """

    def _get_working_form(self):
        """
        Get the parent WorkingForm instance for this object.

        This method must be implemented by subclasses to provide access to the
        parent WorkingForm that contains the approvers list.

        Raises:
            NotImplementedError: If the subclass doesn't implement this method
        """
        raise NotImplementedError

    def calculate_effective_deletion(
        self, total_approvers=None, delete_votes=None
    ) -> bool:
        """
        Calculate whether this item should be considered effectively deleted.

        An item is considered effectively deleted when more than half of the
        approvers have voted for its deletion. This implements a democratic
        deletion mechanism.

        Args:
            total_approvers: Optional pre-calculated count of approvers
            delete_votes: Optional pre-calculated count of deletion votes

        Returns:
            bool: True if the item should be considered effectively deleted,
                  False otherwise
        """
        # If total_approvers not provided, count them from the working form
        if total_approvers is None:
            total_approvers = prefetch_count(self._get_working_form(), "approvers")
        # If delete_votes not provided, count them from this object's deleted_by relation
        if delete_votes is None:
            delete_votes = prefetch_count(self, "deleted_by")
        # If there are no approvers, the item cannot be effectively deleted
        if total_approvers == 0:
            return False
        # Item is effectively deleted if more than half of approvers voted for deletion
        return delete_votes > total_approvers / 2

    @property
    def is_effectively_deleted(self) -> bool:
        """
        Property that indicates whether this item is effectively deleted.

        Returns:
            bool: True if the item is effectively deleted, False otherwise
        """
        return self.calculate_effective_deletion()
