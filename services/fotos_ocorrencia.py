"""Validação e normalização de fotos operacionais, sem metadados EXIF."""

import hashlib
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.datastructures import FileStorage

from utils.arquivos import ErroValidacaoArquivo, validar_arquivo_upload


EXTENSOES_FOTO = {"jpg", "jpeg", "png"}


def preparar_foto(arquivo, limite_bytes):
    nome_original, extensao = validar_arquivo_upload(
        arquivo, EXTENSOES_FOTO, limite_bytes
    )
    formato = "JPEG" if extensao in {"jpg", "jpeg"} else "PNG"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            arquivo.stream.seek(0)
            with Image.open(arquivo.stream) as imagem:
                if imagem.format != formato:
                    raise ErroValidacaoArquivo("Formato da imagem inválido.")
                imagem.load()
                limpa = ImageOps.exif_transpose(imagem)
                limpa = limpa.convert("RGB" if formato == "JPEG" else "RGBA")
                saida = io.BytesIO()
                limpa.save(saida, format=formato)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as erro:
        raise ErroValidacaoArquivo("Imagem inválida ou incompleta.") from erro
    finally:
        arquivo.stream.seek(0)

    dados = saida.getvalue()
    if len(dados) > limite_bytes:
        raise ErroValidacaoArquivo("Arquivo excede o limite máximo permitido de 10 MB.", 413)
    mime = "image/jpeg" if formato == "JPEG" else "image/png"
    nome_final = nome_original.rsplit(".", 1)[0] + (".jpg" if formato == "JPEG" else ".png")
    preparado = FileStorage(stream=io.BytesIO(dados), filename=nome_final, content_type=mime)
    return preparado, nome_original, mime, len(dados), hashlib.sha256(dados).hexdigest()
