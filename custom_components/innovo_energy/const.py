"""Constants for Sigen Energy for ELAN."""

DOMAIN = "innovo_energy"
PLATFORMS = ["sensor", "binary_sensor", "number", "select", "date", "button", "image"]

# options (the same keys Innovo Solar Edge used, so a site moving over keeps its settings)
CONF_PRICE_ENTITY = "energy_price_entity"
CONF_TYPICAL_LOOKUP = "energy_typical_lookup"
CONF_SNAPSHOT_FILE = "energy_snapshot_file"
CONF_PUBLISH_DIR = "energy_publish_dir"
CONF_PUBLISH_PNG = "energy_publish_png"
CONF_BATTERY = "energy_battery"
CONF_PUBLISH_AUTO = "energy_publish_auto"
ENERGY_OPTIONS = (CONF_PRICE_ENTITY, CONF_TYPICAL_LOOKUP, CONF_SNAPSHOT_FILE, CONF_PUBLISH_DIR,
                  CONF_PUBLISH_PNG, CONF_BATTERY, CONF_PUBLISH_AUTO)

# What a universal entity reads when the site's equipment genuinely doesn't have that reading
# (Enphase has no DC side, a solar-only site has no grid meter ...): a controller leaves it out.
#   NA          the equipment doesn't have it - never will, on this site
#   unknown      it has it, but there's no value right now (not reported yet, asleep, faulty)
#   unavailable  Home Assistant's own word: the integration itself isn't running
NOT_AVAILABLE = "NA"

# Innovo Aura (MagicCube) boxes serve this folder over plain HTTP at /icons/
AURA_WEB_ICONS = "/mnt/dietpi_userdata/innovo/www/icons"

# the integration the energy layer used to live in (sites move from it - see migrate.py)
LEGACY_DOMAIN = "innovo_solar_edge"
