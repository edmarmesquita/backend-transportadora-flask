import io
import os
import re
from uuid import uuid4

from PIL import Image, UnidentifiedImageError


LIMITE_LOGO_BYTES = 5 * 1024 * 1024
LIMITE_PIXELS = 8_000_000
EXTENSOES = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG"}
REFERENCIA_LOGO = re.compile(r"^[0-9a-f]{32}\.(?:png|jpg)$")


class LogoInvalido(ValueError):
    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.status = status


def validar_logo(arquivo):
    nome = str(getattr(arquivo, "filename", "") or "")
    if not nome or "/" in nome or "\\" in nome or "." not in nome:
        raise LogoInvalido("Arquivo de logo inválido.")
    extensao = nome.rsplit(".", 1)[1].lower()
    if extensao not in EXTENSOES:
        raise LogoInvalido("Formato de logo não permitido.")

    dados = arquivo.stream.read(LIMITE_LOGO_BYTES + 1)
    if not dados:
        raise LogoInvalido("O arquivo está vazio.")
    if len(dados) > LIMITE_LOGO_BYTES:
        raise LogoInvalido("Logo excede o limite de 5 MiB.", 413)

    try:
        with Image.open(io.BytesIO(dados), formats=("PNG", "JPEG")) as imagem:
            if (imagem.format != EXTENSOES[extensao]
                    or imagem.width * imagem.height > LIMITE_PIXELS
                    or imagem.width < 1 or imagem.height < 1
                    or getattr(imagem, "n_frames", 1) != 1):
                raise LogoInvalido("Conteúdo do logo inválido.")
            imagem.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as erro:
        raise LogoInvalido("Conteúdo do logo inválido.") from erro

    extensao_final = "jpg" if extensao == "jpeg" else extensao
    return dados, f"{uuid4().hex}.{extensao_final}"


def pasta_logos(upload_folder):
    return os.path.join(os.path.abspath(upload_folder), "logos_transportadora")


def caminho_logo(upload_folder, referencia):
    if not isinstance(referencia, str) or not REFERENCIA_LOGO.fullmatch(referencia):
        return None
    pasta_esperada = pasta_logos(upload_folder)
    pasta = os.path.realpath(pasta_esperada)
    if pasta != pasta_esperada:
        return None
    caminho = os.path.join(pasta, referencia)
    if os.path.islink(caminho) or os.path.realpath(caminho) != caminho:
        return None
    return caminho


def logo_existente(upload_folder, referencia):
    caminho = caminho_logo(upload_folder, referencia)
    return caminho if caminho and os.path.isfile(caminho) else None
