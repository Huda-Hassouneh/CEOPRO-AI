"""Framework-neutral MPI subject errors shared by validation and delivery."""


class InvalidSubjectType(ValueError):
    """The requested MPI scope is not one of the three supported scopes."""


class InvalidSubjectIdentifier(ValueError):
    """The requested scope has a malformed or inconsistent identifier."""


class SubjectNotFoundError(LookupError):
    """The subject is absent or is not visible to the authenticated tenant."""
