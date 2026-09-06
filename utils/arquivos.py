import os
import shutil
from uuid import uuid4

from werkzeug.utils import secure_filename


ASSINATURAS_ARQUIVOS = {
    "pdf": b"%PDF-",
    "png": b"\x89PNG\r\n\x1a\n",
    "jpeg": b"\xff\xd8\xff",
}

FORMATOS_POR_EXTENSAO = {
    "pdf": "pdf",
    "png": "png",
    "jpg": "jpeg",
    "jpeg": "jpeg",
}

MIMES_POR_FORMATO = {
    "pdf": {"application/pdf"},
    "png": {"image/png"},
    "jpeg": {"image/jpeg", "image/jpg"},
}

MIMES_GENERICOS = {"", "application/octet-stream"}


class ErroValidacaoArquivo(Exception):
    def __init__(self, mensagem, status_code=400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status_code = status_code


def extensao_arquivo_permitida(nome_arquivo, extensoes_permitidas):
    if not isinstance(nome_arquivo, str) or "." not in nome_arquivo:
        return False

    extensao = nome_arquivo.rsplit(".", 1)[1].lower()

    return bool(extensao) and extensao in extensoes_permitidas


def _obter_tamanho_stream(stream):
    posicao_original = stream.tell()
    stream.seek(0, os.SEEK_END)
    tamanho = stream.tell()
    stream.seek(posicao_original)
    return tamanho


def _detectar_formato(cabecalho):
    for formato, assinatura in ASSINATURAS_ARQUIVOS.items():
        if cabecalho.startswith(assinatura):
            return formato

    return None


def _normalizar_nome_original(nome_arquivo, extensao):
    nome_seguro = secure_filename(nome_arquivo)

    if not nome_seguro or "." not in nome_seguro:
        raise ErroValidacaoArquivo("Arquivo inválido.")

    base = nome_seguro.rsplit(".", 1)[0].strip("._")

    if not base:
        raise ErroValidacaoArquivo("Arquivo inválido.")

    # Reserva espaço para UUID, separador e extensão dentro do campo de 255.
    base = base[:200]
    return f"{base}.{extensao}"


def validar_arquivo_upload(
    arquivo,
    extensoes_permitidas,
    limite_bytes
):
    nome_informado = str(getattr(arquivo, "filename", "") or "").strip()

    if not nome_informado:
        raise ErroValidacaoArquivo("Nenhum arquivo enviado.")

    nome_seguro_inicial = secure_filename(nome_informado)

    if not extensao_arquivo_permitida(
        nome_seguro_inicial,
        extensoes_permitidas
    ):
        raise ErroValidacaoArquivo("Tipo de arquivo não permitido.")

    extensao = nome_seguro_inicial.rsplit(".", 1)[1].lower()
    formato_extensao = FORMATOS_POR_EXTENSAO.get(extensao)

    if not formato_extensao:
        raise ErroValidacaoArquivo("Tipo de arquivo não permitido.")

    stream = arquivo.stream
    stream.seek(0)
    tamanho = _obter_tamanho_stream(stream)

    if tamanho == 0:
        raise ErroValidacaoArquivo("O arquivo está vazio.")

    if tamanho > limite_bytes:
        raise ErroValidacaoArquivo(
            "Arquivo excede o limite máximo permitido de 10 MB.",
            413
        )

    stream.seek(0)
    cabecalho = stream.read(8)
    stream.seek(0)
    formato_detectado = _detectar_formato(cabecalho)

    if not formato_detectado:
        raise ErroValidacaoArquivo("Assinatura do arquivo inválida.")

    if formato_detectado != formato_extensao:
        raise ErroValidacaoArquivo(
            "A extensão do arquivo não corresponde ao conteúdo."
        )

    mimetype = str(getattr(arquivo, "mimetype", "") or "").lower()
    mimes_aceitos = MIMES_POR_FORMATO[formato_detectado]

    if mimetype not in MIMES_GENERICOS and mimetype not in mimes_aceitos:
        raise ErroValidacaoArquivo(
            "O tipo MIME do arquivo não corresponde ao conteúdo."
        )

    nome_original_seguro = _normalizar_nome_original(
        nome_informado,
        extensao
    )

    return nome_original_seguro, extensao


def salvar_arquivo_upload(
    arquivo,
    upload_folder,
    extensoes_permitidas,
    limite_bytes
):
    nome_original_seguro, extensao = validar_arquivo_upload(
        arquivo,
        extensoes_permitidas,
        limite_bytes
    )
    base_original = nome_original_seguro.rsplit(".", 1)[0]
    pasta_destino = os.path.abspath(upload_folder)
    os.makedirs(pasta_destino, exist_ok=True)

    for _tentativa in range(10):
        nome_final = f"{uuid4().hex}_{base_original}.{extensao}"
        caminho = os.path.abspath(os.path.join(pasta_destino, nome_final))

        if os.path.commonpath([pasta_destino, caminho]) != pasta_destino:
            raise ErroValidacaoArquivo("Arquivo inválido.")

        try:
            arquivo.stream.seek(0)

            with open(caminho, "xb") as destino:
                shutil.copyfileobj(arquivo.stream, destino)

            arquivo.stream.seek(0)
            return nome_original_seguro, nome_final, caminho
        except FileExistsError:
            continue
        except Exception:
            if os.path.isfile(caminho):
                try:
                    os.remove(caminho)
                except OSError:
                    pass
            raise

    raise RuntimeError("Não foi possível reservar um nome de arquivo único.")


def remover_arquivo_criado(caminho, logger=None):
    if not caminho or not os.path.isfile(caminho):
        return

    try:
        os.remove(caminho)
    except OSError:
        if logger:
            logger.exception(
                "Falha ao remover arquivo novo após rollback do banco."
            )
