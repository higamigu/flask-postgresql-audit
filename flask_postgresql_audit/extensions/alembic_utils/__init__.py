import alembic_utils
from alembic_utils.experimental import collect_subclasses
from alembic_utils.replaceable_entity import ReplaceableEntity

from .pg_aggregate import PGAggregate

original_types = set(collect_subclasses(alembic_utils, ReplaceableEntity))
extension_types = {PGAggregate}
allowed_types = original_types | extension_types
