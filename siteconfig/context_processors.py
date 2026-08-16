from .models import SiteConfig # Adjust to your actual model

def site_config(request):
    settings = SiteConfig.objects.first()
    return {
        'SITE_NAME': settings.site_name if settings else 'EVE Buyback',
        'SITE_DESCRIPTION': settings.site_description if settings else '',
        'SITE_FOOTER': settings.site_footer if settings else '',
        'SITE_LOGO': settings.site_logo if settings else None,
        'CONTRACT_DEFAULT_DAYS': settings.contract_default_days if settings else 3,
        'CONTRACT_TO': settings.contract_to if settings else '',
        'CONTRACT_STATION': settings.contract_station if settings else '',
    }