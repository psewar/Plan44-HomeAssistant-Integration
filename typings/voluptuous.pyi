# Type checking only: since Home Assistant 2026.9, `voluptuous` resolves to
# probatio at runtime (HA aliases it in sys.modules at startup), and HA types its
# schema parameters with probatio. The integration keeps `import voluptuous as vol`,
# which HA supports for custom integrations and which still works on HA 2026.7 to
# 2026.8. pyright reads this stub (stubPath "typings") instead of the separately
# installed voluptuous, so it checks the code against what HA runs.
# https://contributors.home-assistant.io/blog/2026/09/30/probatio-validation-engine/
from probatio import *  # noqa: F403
