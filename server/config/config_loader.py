"""Configuration loader for environment-specific settings."""

import configparser
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigurationError(Exception):
  """Raised when application configuration is missing or invalid.

  Surfaced in place of silent provider-specific defaults so misconfiguration
  on Azure / GCP deployments fails loudly instead of mislabeling everything
  as AWS / EC2.
  """


class Environment(Enum):
  """Supported deployment environments."""

  DEVELOPMENT = 'dev'
  TEST = 'test'
  STAGING = 'staging'
  PRODUCTION = 'prod'


class CloudPlatform(Enum):
  """Supported cloud platforms."""

  AWS = 'AWS'
  AZURE = 'Azure'
  GCP = 'GCP'


class AppConfig:
  """Application configuration loaded from environment-specific config files."""

  def __init__(self, environment: Optional[str] = None):
    """Initialize configuration loader.

    Args:
        environment: Environment name (dev, test, staging, prod).
                    If None, reads from APP_ENV or defaults to 'dev'.
    """
    self.environment = environment or os.getenv('APP_ENV', 'dev')
    self.config = configparser.ConfigParser()
    self._load_config()

  def _load_config(self) -> None:
    """Load configuration from environment-specific config file."""
    config_dir = Path(__file__).parent.parent.parent / 'config'
    config_file = config_dir / f'app.{self.environment}.config'

    if not config_file.exists():
      # Fallback to development config if environment config doesn't exist
      config_file = config_dir / 'app.dev.config'
      if not config_file.exists():
        raise FileNotFoundError(
          f'Configuration file not found: {config_file}. '
          'Please ensure app.dev.config exists as a fallback.'
        )

    try:
      self.config.read(config_file)
    except Exception as e:
      raise ValueError(f'Error reading configuration file {config_file}: {e}')

  # Cloud Platform Configuration
  @property
  def cloud_platform(self) -> CloudPlatform:
    """Get the configured cloud platform.

    Raises:
        ConfigurationError: when [cloud] platform is missing or set to a
            value outside CloudPlatform. Surfacing this loudly avoids the
            old behavior of silently returning AWS on Azure/GCP deployments.
    """
    platform_str = self.config.get('cloud', 'platform', fallback=None)
    if platform_str is None:
      raise ConfigurationError(
        'Missing [cloud] platform in app config. Set platform = AWS|Azure|GCP.'
      )
    try:
      return CloudPlatform(platform_str)
    except ValueError as exc:
      raise ConfigurationError(
        f"Invalid [cloud] platform value '{platform_str}'. Expected one of: AWS, Azure, GCP."
      ) from exc

  # Databricks Configuration
  @property
  def warehouse_id(self) -> str:
    """Get the SQL warehouse ID."""
    return self.config.get('databricks', 'warehouse_id')

  @property
  def table_name(self) -> str:
    """Get the job spends table name."""
    return self.config.get('databricks', 'table_name')

  @property
  def schema_name(self) -> Optional[str]:
    """Get the schema name."""
    return self.config.get('databricks', 'schema_name', fallback=None)

  @property
  def cluster_spends_table(self) -> Optional[str]:
    """Fully qualified `dbspend360_cluster_spends` table name.

    Resolved off `schema_name` so the new shared-clusters tab does not
    require a separate config key. Returns None when `schema_name` is
    unset (older configs), in which case the Shared Clusters endpoints
    respond with empty / degraded payloads.
    """
    explicit = self.config.get('databricks', 'cluster_spends_table', fallback=None)
    if explicit:
      return explicit
    if self.schema_name:
      return f'{self.schema_name}.dbspend360_cluster_spends'
    return None

  # Feature Flags
  @property
  def enable_cost_analysis(self) -> bool:
    """Check if cost analysis feature is enabled."""
    return self.config.getboolean('features', 'enable_cost_analysis', fallback=True)

  @property
  def enable_shared_clusters_tab(self) -> bool:
    """Check if the Shared Clusters tab is enabled."""
    return self.config.getboolean('features', 'enable_shared_clusters_tab', fallback=True)

  @property
  def enable_instance_pools_tab(self) -> bool:
    """Check if the Instance Pools tab is enabled."""
    return self.config.getboolean('features', 'enable_instance_pools_tab', fallback=True)

  @property
  def enable_cluster_analysis(self) -> bool:
    """Check if cluster analysis feature is enabled."""
    return self.config.getboolean('features', 'enable_cluster_analysis', fallback=True)

  @property
  def enable_ai_insights(self) -> bool:
    """Check if AI insights feature is enabled."""
    return self.config.getboolean('features', 'enable_ai_insights', fallback=True)

  @property
  def enable_export(self) -> bool:
    """Check if export feature is enabled."""
    return self.config.getboolean('features', 'enable_export', fallback=True)

  # Performance Configuration
  @property
  def query_timeout_seconds(self) -> int:
    """Get query timeout in seconds."""
    return self.config.getint('performance', 'query_timeout_seconds', fallback=30)

  @property
  def cache_ttl_minutes(self) -> int:
    """Get cache TTL in minutes."""
    return self.config.getint('performance', 'cache_ttl_minutes', fallback=5)

  @property
  def max_results_per_page(self) -> int:
    """Get maximum results per page."""
    return self.config.getint('performance', 'max_results_per_page', fallback=100)

  # Logging Configuration
  @property
  def log_level(self) -> str:
    """Get log level."""
    return self.config.get('logging', 'log_level', fallback='INFO').upper()

  @property
  def enable_debug_endpoints(self) -> bool:
    """Check if debug endpoints are enabled."""
    return self.config.getboolean('logging', 'enable_debug_endpoints', fallback=False)

  # Cloud Platform Specific Methods
  def get_compute_service_name(self) -> str:
    """Get the compute service name based on cloud platform.

    Raises:
        ConfigurationError: if the resolved cloud platform has no entry
            in the mapping. Replaces the old silent EC2 default.
    """
    platform_mappings = {
      CloudPlatform.AWS: 'EC2',
      CloudPlatform.AZURE: 'Azure Compute',
      CloudPlatform.GCP: 'GCE',
    }
    try:
      return platform_mappings[self.cloud_platform]
    except KeyError as exc:
      raise ConfigurationError(
        f'No compute service name mapping for platform {self.cloud_platform!r}.'
      ) from exc

  def get_compute_display_name(self) -> str:
    """Get the compute cost display name."""
    return f'{self.get_compute_service_name()} Cost'

  def get_platform_display_name(self) -> str:
    """Get the platform display name.

    Raises:
        ConfigurationError: if the resolved cloud platform has no entry
            in the mapping. Replaces the old silent AWS default.
    """
    platform_mappings = {
      CloudPlatform.AWS: 'AWS',
      CloudPlatform.AZURE: 'Azure',
      CloudPlatform.GCP: 'Google Cloud',
    }
    try:
      return platform_mappings[self.cloud_platform]
    except KeyError as exc:
      raise ConfigurationError(
        f'No platform display name mapping for platform {self.cloud_platform!r}.'
      ) from exc

  def get_cost_breakdown_labels(self) -> Dict[str, str]:
    """Get labels for cost breakdown charts and displays."""
    return {
      'compute_cost': self.get_compute_display_name(),
      'databricks_cost': 'Databricks Cost',
      'platform': self.get_platform_display_name(),
      'compute_service': self.get_compute_service_name(),
    }

  def to_dict(self) -> Dict[str, Any]:
    """Convert configuration to dictionary format."""
    return {
      'environment': self.environment,
      'cloud': {
        'platform': self.cloud_platform.value,
        'compute_service': self.get_compute_service_name(),
        'compute_display_name': self.get_compute_display_name(),
        'platform_display_name': self.get_platform_display_name(),
      },
      'databricks': {
        'warehouse_id': self.warehouse_id,
        'table_name': self.table_name,
        'schema_name': self.schema_name,
      },
      'features': {
        'enable_cost_analysis': self.enable_cost_analysis,
        'enable_cluster_analysis': self.enable_cluster_analysis,
        'enable_ai_insights': self.enable_ai_insights,
        'enable_export': self.enable_export,
        'enable_shared_clusters_tab': self.enable_shared_clusters_tab,
        'enable_instance_pools_tab': self.enable_instance_pools_tab,
      },
      'performance': {
        'query_timeout_seconds': self.query_timeout_seconds,
        'cache_ttl_minutes': self.cache_ttl_minutes,
        'max_results_per_page': self.max_results_per_page,
      },
      'logging': {
        'log_level': self.log_level,
        'enable_debug_endpoints': self.enable_debug_endpoints,
      },
    }


# Global configuration instance
app_config = AppConfig()
