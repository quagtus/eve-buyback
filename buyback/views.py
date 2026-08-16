from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django_ratelimit.decorators import ratelimit

from buyback.domain.gateway import AppraisalError
from buyback.models import Quote
from buyback.services import (
    DuplicateQuoteError,
    EmptyAppraisalError,
    build_default_gateway,
    generate_quote,
)
from siteconfig.models import SiteConfig


def form(request):
    return render(
        request, "buyback/form.html", {"config": SiteConfig.load()}
    )


def _error(request, message, status=200):
    return render(request, "buyback/_error.html", {"message": message}, status=status)


def _redirect_to_quote(request, quote):
    """Send the browser to the permanent quote URL.

    HTMX issues the POST via fetch(), which follows a normal 302 transparently
    and hands HTMX the FINAL response body to swap into the target element —
    the entire quote page would end up nested inside the form page's
    #result div, and the address bar would never change. HX-Redirect tells
    HTMX to instead perform a real client-side navigation, so the seller
    lands on the actual shareable URL. Non-HTMX (plain form, no JS) requests
    get a normal redirect so the page still works without JavaScript.
    """
    url = reverse("buyback:quote", kwargs={"code": quote.pk})
    if request.headers.get("HX-Request"):
        response = HttpResponse(status=200)
        response["HX-Redirect"] = url
        return response
    return redirect(url)


# block=False: django-ratelimit 4.x defaults to block=True, which raises
# Ratelimited and returns a bare 403 before this view ever runs. We want our
# own 429 response with a message, so we let the decorator just annotate
# request.limited and check it below, before any expensive work happens.
@ratelimit(
    key="ip",
    rate=lambda g, r: settings.BUYBACK_RATE_LIMIT,
    method="POST",
    block=False,
)
def submit(request):
    if request.method != "POST":
        return redirect("buyback:form")

    if getattr(request, "limited", False):
        return _error(
            request, _("Too many quotes requested. Please try again later."), status=429
        )

    raw_text = (request.POST.get("raw_text") or "").strip()
    if not raw_text:
        return _error(request, _("Paste your items before requesting a quote."))

    try:
        quote = generate_quote(raw_text, build_default_gateway())
    except EmptyAppraisalError:
        return _error(request, _("None of those lines could be priced."))
    except DuplicateQuoteError:
        return _error(request, _("That quote already exists. Please try again."))
    except AppraisalError:
        return _error(
            request, _("The price service is unavailable right now. Please try again.")
        )

    return _redirect_to_quote(request, quote)


def quote(request, code):
    instance = get_object_or_404(
        Quote.objects.prefetch_related("items"), pk=code
    )
    return render(request, "buyback/quote.html", {"quote": instance})
