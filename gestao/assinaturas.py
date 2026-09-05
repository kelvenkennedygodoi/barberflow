from .models import Assinatura


def obter_assinatura(barbearia):
    assinatura = Assinatura.objects.filter(barbearia=barbearia).first()
    if assinatura is None:
        return None
    assinatura.sincronizar_expiracao()
    return assinatura


def barbearia_tem_acesso(barbearia):
    if not barbearia or not barbearia.ativa:
        return False
    assinatura = obter_assinatura(barbearia)
    return bool(assinatura and assinatura.acesso_liberado())
