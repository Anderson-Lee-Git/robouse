"""SPH liquid for household scene packages (liquid contracts 1.0.0 and 1.1.0, CPU): DFSPH through a pinned
SPlisHSPlasH build, one-way coupled to MuJoCo, with particle accounting (containers, work surface, absorbers,
per-source identity), a validated static domain and a rendered surface. Registered in extensions.py under the
episode.json key `liquid`.

Modules: `config` (the episode.json block, strict), `solver` (backend pin and the validated fluid), `domain` (static
boxes, continuous contact, validity), `meshes`, `contact` (mesh distance, absorbers, sleep), `queries` (labels,
volumes, puddle), `surface` (rendered mesh), `extension` (the hooks and the goal queries).

Importing this package needs only numpy and MuJoCo; the native solver loads when a liquid episode is built.
"""

from .config import CONTRACT
from .domain import LiquidValidityError
from .extension import Extension, release

__all__ = ["CONTRACT", "Extension", "LiquidValidityError", "release"]
