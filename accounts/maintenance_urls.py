from django.urls import path
from .maintenance import FORM_TYPES, workspace

urlpatterns = [path("", workspace, name="maintenance")]
urlpatterns += [path(name + "/", workspace, {"action": name}) for name in FORM_TYPES]
