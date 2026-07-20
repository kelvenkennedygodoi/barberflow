from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied


class BarbeariaObrigatoriaMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_superuser and not request.user.barbearia_id:
            raise PermissionDenied("Seu usuário não está vinculado a uma barbearia.")
        return super().dispatch(request, *args, **kwargs)


class GestorObrigatorioMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.pode_gerenciar


class QuerysetDaBarbeariaMixin(BarbeariaObrigatoriaMixin):
    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_superuser and not self.request.user.barbearia_id:
            return queryset
        return queryset.filter(barbearia=self.request.user.barbearia)


class FormDaBarbeariaMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if "barbearia" in self.form_class.__init__.__code__.co_varnames:
            kwargs["barbearia"] = self.request.user.barbearia
        return kwargs

    def form_valid(self, form):
        form.instance.barbearia = self.request.user.barbearia
        return super().form_valid(form)
