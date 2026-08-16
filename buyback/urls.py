from django.urls import path

from buyback import views

app_name = "buyback"

urlpatterns = [
    path("", views.form, name="form"),
    path("submit/", views.submit, name="submit"),
    path("quote/<str:code>/", views.snapshot, name="snapshot"),
]
