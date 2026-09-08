from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from models.clientes import Cliente, ClienteUsuario
from models.recursos import Motorista
from models.usuarios import UsuarioSistema
from services.auditoria import registrar_log
from utils.senhas import gerar_hash_senha, senha_esta_em_hash


admin_usuarios_bp = Blueprint(
    "admin_usuarios",
    __name__
)


def _usuario_e_ultimo_administrador_ativo(usuario):
    if not usuario or not usuario.ativo:
        return False

    if str(usuario.perfil).strip().lower() != "administrador":
        return False

    quantidade = UsuarioSistema.query.filter(
        UsuarioSistema.ativo.is_(True),
        db.func.lower(db.func.trim(UsuarioSistema.perfil)) == "administrador",
    ).count()

    return quantidade <= 1


@admin_usuarios_bp.route(
    "/api/admin/usuarios/<int:id>/inativar",
    methods=["POST"]
)
@jwt_required()
def api_inativar_usuario(id):
    usuario_logado_id = int(get_jwt_identity())
    usuario_logado = db.session.get(
        UsuarioSistema,
        usuario_logado_id
    )

    if not usuario_logado or not usuario_logado.ativo:
        return jsonify({
            "erro": "Usuário autenticado não autorizado."
        }), 401

    if str(usuario_logado.perfil).strip().lower() != "administrador":
        return jsonify({
            "erro": "Apenas administradores podem inativar usuários."
        }), 403

    usuario = db.session.get(
        UsuarioSistema,
        id
    )

    if not usuario:
        return jsonify({
            "erro": "Usuário não encontrado."
        }), 404

    if usuario.id == usuario_logado.id:
        return jsonify({
            "erro": "Você não pode inativar o próprio usuário."
        }), 400

    if not usuario.ativo:
        return jsonify({
            "mensagem": "Este usuário já está inativo."
        }), 200

    if _usuario_e_ultimo_administrador_ativo(usuario):
        return jsonify({
            "erro": "Não é possível inativar o último administrador ativo."
        }), 409

    try:
        dados_antes = {
            "ativo": usuario.ativo
        }

        usuario.ativo = False

        registrar_log(
            acao="Inativação de usuário",
            detalhes=(
                f"O usuário {usuario_logado.nome} "
                f"inativou {usuario.nome}."
            ),
            modulo="Usuários",
            entidade="UsuarioSistema",
            entidade_id=usuario.id,
            antes=dados_antes,
            depois={
                "ativo": usuario.ativo
            },
            usuario_id=usuario_logado.id,
            usuario_nome=usuario_logado.nome,
            perfil=usuario_logado.perfil
        )
        db.session.commit()

        return jsonify({
            "mensagem": "Usuário inativado com sucesso!"
        }), 200

    except Exception as erro:
        db.session.rollback()

        print(
            "ERRO AO INATIVAR USUÁRIO:",
            erro
        )

        return jsonify({
            "erro": "Não foi possível inativar o usuário."
        }), 500


@admin_usuarios_bp.route(
    "/api/admin/usuarios/<int:id>",
    methods=["GET"]
)
@jwt_required()
def api_buscar_usuario(id):
    usuario_logado_id = int(get_jwt_identity())

    usuario_logado = db.session.get(
        UsuarioSistema,
        usuario_logado_id
    )

    if not usuario_logado or not usuario_logado.ativo:
        return jsonify({
            "erro": "Usuário autenticado não autorizado."
        }), 401

    if str(usuario_logado.perfil).strip().lower() != "administrador":
        return jsonify({
            "erro": "Apenas administradores podem gerenciar usuários."
        }), 403

    usuario = db.session.get(
        UsuarioSistema,
        id
    )

    if not usuario:
        return jsonify({
            "erro": "Usuário não encontrado."
        }), 404

    cliente_usuario = ClienteUsuario.query.filter_by(
        usuario_sistema_id=usuario.id
    ).first()

    return jsonify({
        "id": usuario.id,
        "nome": usuario.nome,
        "usuario": usuario.usuario,
        "email": usuario.email or "",
        "perfil": usuario.perfil,
        "ativo": usuario.ativo,
        "cliente_id": (
            cliente_usuario.cliente_id
            if cliente_usuario
            else None
        ),
    }), 200

@admin_usuarios_bp.route(
   "/api/admin/usuarios",
    methods=["GET", "POST"]
)
@jwt_required()
def api_admin_usuarios():
    usuario_logado_id = int(get_jwt_identity())

    usuario_logado = db.session.get(
        UsuarioSistema,
        usuario_logado_id
    )

    if not usuario_logado or not usuario_logado.ativo:
        return jsonify({
            "erro": "Usuário não autorizado."
        }), 401

    if str(usuario_logado.perfil).strip().lower() != "administrador":
        return jsonify({
            "erro": "Apenas administradores podem gerenciar usuários."
        }), 403

    if request.method == "GET":
        usuarios = UsuarioSistema.query.order_by(
            UsuarioSistema.data_criacao.desc()
        ).all()

        lista = []

        for usuario in usuarios:
            lista.append({
                "id": usuario.id,
                "nome": usuario.nome,
                "email": usuario.email or "",
                "usuario": usuario.usuario,
                "perfil": usuario.perfil,
                "ativo": usuario.ativo,
                "data_criacao": (
                    usuario.data_criacao.strftime(
                        "%d/%m/%Y %H:%M"
                    )
                    if usuario.data_criacao
                    else ""
                )
            })

        return jsonify(lista), 200

    dados = request.get_json(silent=True) or {}

    nome = str(dados.get("nome", "")).strip()
    email = str(dados.get("email", "")).strip().lower()
    nome_usuario = str(
        dados.get("usuario", "")
    ).strip()
    senha = str(dados.get("senha", "")).strip()
    perfil = str(
        dados.get("perfil", "operador")
    ).strip().lower()

    if not nome or not nome_usuario or not senha:
        return jsonify({
            "erro": "Nome, usuário e senha são obrigatórios."
        }), 400

    if len(senha) < 6:
        return jsonify({
            "erro": "A senha deve ter pelo menos 6 caracteres."
        }), 400

    perfis_permitidos = [
        "administrador",
        "operador",
        "motorista",
        "cliente"
    ]

    if perfil not in perfis_permitidos:
        return jsonify({
            "erro": "Perfil inválido."
        }), 400

    cliente_comercial = None

    if perfil == "cliente":
        if not email:
            return jsonify({
                "erro": "O e-mail é obrigatório para usuários clientes."
            }), 400

        cliente_id = dados.get("cliente_id")

        try:
            cliente_id = int(cliente_id)
        except (TypeError, ValueError):
            return jsonify({
                "erro": "Selecione um cliente comercial ativo."
            }), 400

        cliente_comercial = db.session.get(
            Cliente,
            cliente_id
        )

        if not cliente_comercial or not cliente_comercial.ativo:
            return jsonify({
                "erro": "Selecione um cliente comercial ativo."
            }), 400

    usuario_existente = UsuarioSistema.query.filter_by(
        usuario=nome_usuario
    ).first()

    if usuario_existente:
        return jsonify({
            "erro": "Este nome de usuário já está cadastrado."
        }), 409

    if email:
        email_existente = UsuarioSistema.query.filter_by(
            email=email
        ).first()

        if email_existente:
            return jsonify({
                "erro": "Este e-mail já está cadastrado no sistema."
            }), 409

        if perfil == "cliente":
            cliente_existente = ClienteUsuario.query.filter_by(
                email=email
            ).first()

            if cliente_existente:
                return jsonify({
                    "erro": (
                        "Já existe um cliente cadastrado "
                        "com este e-mail."
                    )
                }), 409

    try:
        senha_hash = gerar_hash_senha(senha)

        novo_usuario = UsuarioSistema(
            nome=nome,
            email=email,
            usuario=nome_usuario,
            senha=senha_hash,
            perfil=perfil,
            ativo=True
        )

        db.session.add(novo_usuario)
        db.session.flush()

        if perfil == "cliente":
            cliente_login = ClienteUsuario(
                usuario_sistema_id=novo_usuario.id,
                cliente_id=cliente_comercial.id,
                nome=nome,
                empresa=cliente_comercial.razao_social,
                email=email,
                senha=senha_hash,
                ativo=novo_usuario.ativo
            )

            db.session.add(cliente_login)

        if perfil == "motorista":
            motorista_existente = Motorista.query.filter_by(
                usuario=nome_usuario
            ).first()

            if motorista_existente:
                db.session.rollback()

                return jsonify({
                    "erro": (
                        "Já existe um motorista com "
                        "este nome de usuário."
                    )
                }), 409

            motorista = Motorista(
                nome=nome,
                email=email,
                usuario=nome_usuario,
                senha=senha_hash,
                status="Ativo"
            )

            motorista.usuario_sistema = novo_usuario

            db.session.add(motorista)

        registrar_log(
            acao="Criação de usuário",
            detalhes=f"O usuário {usuario_logado.nome} criou {novo_usuario.nome}.",
            modulo="Usuários",
            entidade="UsuarioSistema",
            entidade_id=novo_usuario.id,
            antes=None,
            depois={
                "nome": novo_usuario.nome,
                "usuario": novo_usuario.usuario,
                "email": novo_usuario.email or "",
                "perfil": novo_usuario.perfil,
                "ativo": novo_usuario.ativo,
                "senha_definida": True,
            },
            usuario_id=usuario_logado.id,
            usuario_nome=usuario_logado.nome,
            perfil=usuario_logado.perfil
        )
        db.session.commit()

        return jsonify({
            "mensagem": "Usuário criado com sucesso!"
        }), 201

    except Exception as erro:
        db.session.rollback()

        print(
            "ERRO AO CRIAR USUÁRIO:",
            erro
        )

        return jsonify({
            "erro": "Não foi possível criar o usuário."
        }), 500


@admin_usuarios_bp.route(
    "/api/admin/usuarios/<int:id>",
    methods=["PUT"]
)
@jwt_required()
def api_editar_usuario(id):
    usuario_logado_id = int(get_jwt_identity())

    usuario_logado = db.session.get(
        UsuarioSistema,
        usuario_logado_id
    )

    if not usuario_logado or not usuario_logado.ativo:
        return jsonify({
            "erro": "Usuário autenticado não autorizado."
        }), 401

    if str(usuario_logado.perfil).strip().lower() != "administrador":
        return jsonify({
            "erro": "Apenas administradores podem editar usuários."
        }), 403

    usuario = db.session.get(
        UsuarioSistema,
        id
    )

    if not usuario:
        return jsonify({
            "erro": "Usuário não encontrado."
        }), 404

    dados = request.get_json(silent=True) or {}

    nome = str(
        dados.get("nome", usuario.nome)
    ).strip()

    nome_usuario = str(
        dados.get("usuario", usuario.usuario)
    ).strip()

    email = str(
        dados.get("email", usuario.email or "")
    ).strip()

    perfil = str(
        dados.get("perfil", usuario.perfil)
    ).strip().lower()

    ativo = dados.get(
        "ativo",
        usuario.ativo
    )

    if (
        _usuario_e_ultimo_administrador_ativo(usuario)
        and (perfil != "administrador" or not bool(ativo))
    ):
        return jsonify({
            "erro": (
                "O último administrador ativo não pode ser inativado "
                "nem perder o perfil administrador."
            )
        }), 409

    if not nome:
        return jsonify({
            "erro": "Informe o nome."
        }), 400

    if not nome_usuario:
        return jsonify({
            "erro": "Informe o usuário."
        }), 400

    perfis_permitidos = [
        "administrador",
        "operador",
        "motorista",
        "cliente"
    ]

    if perfil not in perfis_permitidos:
        return jsonify({
            "erro": "Perfil inválido."
        }), 400

    perfil_anterior = str(
        usuario.perfil
    ).strip().lower()

    cliente_usuario = ClienteUsuario.query.filter_by(
        usuario_sistema_id=usuario.id
    ).first()

    cliente_comercial = None

    if perfil == "cliente":
        if not email:
            return jsonify({
                "erro": "O e-mail é obrigatório para usuários clientes."
            }), 400

        cliente_id = dados.get("cliente_id")

        try:
            cliente_id = int(cliente_id)
        except (TypeError, ValueError):
            return jsonify({
                "erro": "Selecione um cliente comercial ativo."
            }), 400

        cliente_comercial = db.session.get(
            Cliente,
            cliente_id
        )

        cliente_atual_inativo = (
            perfil_anterior == "cliente"
            and cliente_usuario
            and cliente_usuario.cliente_id == cliente_id
        )

        if (
            not cliente_comercial
            or (
                not cliente_comercial.ativo
                and not cliente_atual_inativo
            )
        ):
            return jsonify({
                "erro": "Selecione um cliente comercial ativo."
            }), 400

        if not cliente_usuario:
            cliente_legado = ClienteUsuario.query.filter_by(
                email=email,
                usuario_sistema_id=None
            ).first()

            if cliente_legado:
                return jsonify({
                    "erro": (
                        "Já existe um acesso de cliente legado "
                        "com este e-mail. Regularize o vínculo "
                        "antes de alterar o perfil."
                    )
                }), 409

    usuario_duplicado = UsuarioSistema.query.filter(
        UsuarioSistema.usuario == nome_usuario,
        UsuarioSistema.id != usuario.id
    ).first()

    if usuario_duplicado:
        return jsonify({
            "erro": "Este nome de usuário já está cadastrado."
        }), 409

    if email:
        email_duplicado = UsuarioSistema.query.filter(
            UsuarioSistema.email == email,
            UsuarioSistema.id != usuario.id
        ).first()

        if email_duplicado:
            return jsonify({
                "erro": "Este e-mail já está cadastrado no sistema."
            }), 409

        consulta_cliente_email = ClienteUsuario.query.filter(
            ClienteUsuario.email == email
        )

        if cliente_usuario:
            consulta_cliente_email = consulta_cliente_email.filter(
                ClienteUsuario.id != cliente_usuario.id
            )

        cliente_email_duplicado = consulta_cliente_email.first()

        if (
            cliente_email_duplicado
            and (
                perfil == "cliente"
                or cliente_email_duplicado.email
                != (usuario.email or "")
            )
        ):
            return jsonify({
                "erro": (
                    "Este e-mail já está vinculado "
                    "a outro cliente."
                )
            }), 409

    redefinir_senha = bool(
        dados.get("redefinir_senha", False)
    )

    nova_senha = str(
        dados.get("nova_senha", "")
    ).strip()

    if redefinir_senha and len(nova_senha) < 6:
        return jsonify({
            "erro": (
                "A nova senha deve ter "
                "pelo menos 6 caracteres."
            )
        }), 400

    dados_antes = {
        "nome": usuario.nome,
        "usuario": usuario.usuario,
        "email": usuario.email or "",
        "perfil": usuario.perfil,
        "ativo": usuario.ativo,
    }

    try:
        usuario.nome = nome
        usuario.usuario = nome_usuario
        usuario.email = email
        usuario.perfil = perfil
        usuario.ativo = bool(ativo)

        if redefinir_senha:
            usuario.senha = gerar_hash_senha(nova_senha)

        if perfil == "cliente":
            if not cliente_usuario:
                if not senha_esta_em_hash(usuario.senha):
                    usuario.senha = gerar_hash_senha(
                        usuario.senha
                    )

                cliente_usuario = ClienteUsuario(
                    usuario_sistema_id=usuario.id,
                    cliente_id=cliente_comercial.id,
                    nome=nome,
                    empresa=cliente_comercial.razao_social,
                    email=email,
                    senha=usuario.senha,
                    ativo=usuario.ativo
                )

                db.session.add(cliente_usuario)
            else:
                cliente_usuario.cliente_id = cliente_comercial.id
                cliente_usuario.empresa = cliente_comercial.razao_social
                cliente_usuario.nome = nome
                cliente_usuario.email = email
                cliente_usuario.ativo = usuario.ativo

        if redefinir_senha:
            if cliente_usuario:
                cliente_usuario.senha = usuario.senha

            motorista_usuario = Motorista.query.filter_by(
                usuario_sistema_id=usuario.id
            ).first()

            if motorista_usuario:
                motorista_usuario.senha = usuario.senha

        dados_depois = {
            "nome": usuario.nome,
            "usuario": usuario.usuario,
            "email": usuario.email or "",
            "perfil": usuario.perfil,
            "ativo": usuario.ativo,
            "senha_redefinida": redefinir_senha,
        }

        registrar_log(
            acao="Edição de usuário",
            detalhes=(
                f"O usuário {usuario_logado.nome} "
                f"alterou o cadastro de {usuario.nome}."
            ),
            modulo="Usuários",
            entidade="UsuarioSistema",
            entidade_id=usuario.id,
            antes=dados_antes,
            depois=dados_depois,
            usuario_id=usuario_logado.id,
            usuario_nome=usuario_logado.nome,
            perfil=usuario_logado.perfil
        )
        db.session.commit()

        return jsonify({
            "mensagem": "Usuário atualizado com sucesso!"
        }), 200

    except Exception as erro:
        db.session.rollback()

        print(
            "ERRO AO EDITAR USUÁRIO:",
            erro
        )

        return jsonify({
            "erro": "Não foi possível atualizar o usuário."
        }), 500
