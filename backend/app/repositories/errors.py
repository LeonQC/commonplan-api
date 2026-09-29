class RepositoryConflictError(Exception):
    """Raised when a persistence write violates a database constraint."""
