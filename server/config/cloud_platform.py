"""Cloud platform configuration for dynamic compute service naming."""

from server.config.config_loader import app_config


class CloudConfig:
  """Configuration for cloud-specific terminology and labels using config files."""

  @property
  def platform(self):
    """Get the configured cloud platform."""
    return app_config.cloud_platform

  @property
  def compute_service_name(self) -> str:
    """Get the compute service name (e.g., 'EC2', 'Azure Compute', 'GCE')."""
    return app_config.get_compute_service_name()

  @property
  def compute_display_name(self) -> str:
    """Get the compute cost display name (e.g., 'EC2 Cost', 'Azure Compute Cost')."""
    return app_config.get_compute_display_name()

  @property
  def platform_display_name(self) -> str:
    """Get the platform display name (e.g., 'AWS', 'Azure', 'Google Cloud')."""
    return app_config.get_platform_display_name()

  def get_cost_breakdown_labels(self) -> dict[str, str]:
    """Get labels for cost breakdown charts and displays."""
    return app_config.get_cost_breakdown_labels()


# Global cloud configuration instance
cloud_config = CloudConfig()
