import enum


class Docstatus(enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"
    REVISED = "revised"
