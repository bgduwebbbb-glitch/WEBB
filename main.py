import os
import time
import json
import asyncio
import aiohttp
import discord
from discord import app_commands
from flask import Flask, request, jsonify
from threading import Thread

# --- SERVEUR WEB (POUR UPTIMEROBOT & WEBHOOKS) ---
app = Flask('')

@app.route('/')
def home():
    return "Le bot de génération et d'abonnements est en ligne !"

def run_web():
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = discord.Object(id=1548782928492892170)
OWNER_ROLE_ID = 1548786678796128547  # Rôle Owner

# IDs des salons
LOG_CHANNEL_ID = 1549864719618146335
STOCK_CHANNEL_ID = 1548788811046330458
SUGGESTION_CHANNEL_ID = 1548792739091583006
PURCHASE_LOG_CHANNEL_ID = 1550226577814585344
ACHETEUR_NOTIF_CHANNEL_ID = 1550526888559120404  # Salon de notification des acheteurs
LEADERBOARD_CHANNEL_ID = 1550244499115217017  # Salon du leaderboard des gens

# IDs des rôles
ROLE_ACHETEUR = 1548788762992185556  # Rôle Acheteur
ROLE_CM = 1550248011085512705         # Rôle CM

# URL d'achat du produit
URL_ACHAT = "https://k4lyx-gen.mysellauth.com/product/gen-account"

# Fichiers JSON
ROLES_FILE = "active_roles.json"
STATS_FILE = "gen_stats.json"
PERMS_STATE_FILE = "perms_state.json"

# Clé API SellAuth
SELLAUTH_API_KEY = os.getenv("SELLAUTH_API_KEY")
SELLAUTH_SHOP_ID = "268775"

ALL_SERVICES = [
    "eldorado", "eneba", "epicgames", "xbox", 
    "hotmail", "crunchyroll", "start", "starpets", 
    "roblox", "instantgaming", "steam",
    "basicfit", "riotgames", "onoff", "mulvaldvpn"
]

# Dictionnaire pour gérer le cooldown de la commande /gen
gen_cooldowns = {}
COOLDOWN_SECONDS = 5  # Valeur par défaut modifiable via /cooldown

def is_owner_user(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    if interaction.user.id == interaction.guild.owner_id:
        return True
    if isinstance(interaction.user, discord.Member):
        return any(role.id == OWNER_ROLE_ID for role in interaction.user.roles)
    return False

# --- GESTION JSON ---
def load_json_file(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_json_file(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def increment_gen_stat(user_id: int):
    stats = load_json_file(STATS_FILE)
    user_str = str(user_id)
    stats[user_str] = stats.get(user_str, 0) + 1
    save_json_file(STATS_FILE, stats)

# --- VERIFICATION ACCÈS COMMANDE /GEN ---
def get_perms_state():
    state = load_json_file(PERMS_STATE_FILE)
    if "acheteur_enabled" not in state:
        state["acheteur_enabled"] = True
    if "cm_expire_at" not in state:
        state["cm_expire_at"] = 0
    return state

def set_perms_state(state):
    save_json_file(PERMS_STATE_FILE, state)

def can_user_gen(member: discord.Member) -> bool:
    if any(role.id == OWNER_ROLE_ID for role in member.roles) or member.id == member.guild.owner_id:
        return True
    
    state = get_perms_state()
    current_time = time.time()

    has_acheteur = any(role.id == ROLE_ACHETEUR for role in member.roles)
    if has_acheteur and state.get("acheteur_enabled", True):
        return True

    has_cm = any(role.id == ROLE_CM for role in member.roles)
    cm_expire_at = state.get("cm_expire_at", 0)
    if has_cm and current_time < cm_expire_at:
        return True

    return False

# --- REPONSE REFUS D'ACCES AVEC BOUTON D'ACHAT (PUBLIC) ---
async def send_no_permission_response(interaction: discord.Interaction):
    view = discord.ui.View()
    button = discord.ui.Button(
        label="Acheter un accès / Gen",
        url=URL_ACHAT,
        style=discord.ButtonStyle.link,
        emoji="🛒"
    )
    view.add_item(button)

    embed = discord.Embed(
        title="❌ Accès Refusé",
        description=(
            f"Vous n'avez pas la permission d'utiliser la commande `/gen`.\n\n"
            f"Pour obtenir votre accès, achetez le grade ici :\n{URL_ACHAT}"
        ),
        color=discord.Color.red()
    )

    if interaction.response.is_done():
        await interaction.followup.send(content=f"{interaction.user.mention}", embed=embed, view=view, ephemeral=False)
    else:
        await interaction.response.send_message(content=f"{interaction.user.mention}", embed=embed, view=view, ephemeral=False)

# --- MISE À JOUR DU STOCK ---
async def update_live_stock(client: discord.Client):
    stock_channel = client.get_channel(STOCK_CHANNEL_ID)
    if not stock_channel:
        return

    embed = discord.Embed(
        title="🌟 ─── [ 📦 LIVE SHOP STOCK ] ─── 🌟",
        description="Bienvenue sur le stock officiel de notre boutique !\n*Les stocks sont actualisés en temps réel.*\n\n━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.from_rgb(47, 49, 54)
    )
    
    stock_lines = []
    for service in ALL_SERVICES:
        filename = f"stock_{service}.txt"
        count = 0
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                count = sum(1 for line in f if line.strip() and ":" in line)
        
        status_icon = "🟢" if count > 0 else "🔴"
        
        if service == "epicgames": formatted_name = "Epic Games"
        elif service == "instantgaming": formatted_name = "Instant Gaming"
        elif service == "starpets": formatted_name = "StarPets"
        elif service == "basicfit": formatted_name = "Basic-Fit"
        elif service == "riotgames": formatted_name = "Riot Games"
        elif service == "onoff": formatted_name = "OnOff"
        elif service == "mulvaldvpn": formatted_name = "Mulvald VPN"
        else: formatted_name = service.capitalize()

        stock_lines.append(f"{status_icon} **{formatted_name}** ➔ `{count}` disponible(s)")

    embed.add_field(
        name="📊 **DISPONIBILITÉS DES SERVICES**",
        value="\n".join(stock_lines),
        inline=False
    )

    embed.add_field(
        name="💡 **UNE ENVIE PARTICULIÈRE ?**",
        value=f"Si vous souhaitez d'autres services, dites-le nous dans le salon <#{SUGGESTION_CHANNEL_ID}> et nous les ajouterons pour vous !",
        inline=False
    )

    embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/3081/3081559.png")
    embed.set_footer(text="✨ Système automatisé • Boutique officielle 24/7", icon_url="https://cdn-icons-png.flaticon.com/512/10313/10313217.png")

    async for message in stock_channel.history(limit=10):
        if message.author == client.user and message.embeds and "LIVE SHOP STOCK" in message.embeds[0].title:
            await message.edit(embed=embed)
            return
            
    await stock_channel.send(embed=embed)

# --- MISE À JOUR DU LEADERBOARD EN LIVE ---
async def update_live_leaderboard(client: discord.Client):
    lb_channel = client.get_channel(LEADERBOARD_CHANNEL_ID)
    if not lb_channel:
        return

    stats = load_json_file(STATS_FILE)
    sorted_stats = sorted(stats.items(), key=lambda item: item[1], reverse=True)[:10]

    embed = discord.Embed(
        title="🏆 ─── [ CLASSEMENT DES GÉNÉRATIONS ] ─── 🏆",
        description="Voici le classement en direct des membres ayant généré le plus de comptes !\n\n━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.gold()
    )

    if not sorted_stats:
        embed.add_field(name="📊 Top Membres", value="*Aucune génération enregistrée pour le moment.*", inline=False)
    else:
        lb_lines = []
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for index, (user_id_str, count) in enumerate(sorted_stats):
            medal = medals[index] if index < len(medals) else f"`{index+1}.`"
            lb_lines.append(f"{medal} <@{user_id_str}> ➔ **{count}** génération(s)")
        
        embed.add_field(name="📊 **TOP 10 DES GENS**", value="\n".join(lb_lines), inline=False)

    embed.set_footer(text="✨ Mis à jour en temps réel • Système de stats", icon_url="https://cdn-icons-png.flaticon.com/512/3112/3112946.png")

    async for message in lb_channel.history(limit=10):
        if message.author == client.user and message.embeds and "CLASSEMENT DES GÉNÉRATIONS" in message.embeds[0].title:
            await message.edit(embed=embed)
            return
            
    await lb_channel.send(embed=embed)


# --- MODALS ET VUES PANELS ---

class CmTimeModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Gestion du temps CM")

        self.time_input = discord.ui.TextInput(
            label="Temps à ajouter (en minutes)",
            style=discord.TextStyle.short,
            placeholder="Exemple: 30",
            required=True,
            max_length=5
        )
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_owner_user(interaction):
            await interaction.response.send_message("❌ Action réservée au rôle Owner.", ephemeral=True)
            return

        try:
            minutes = int(self.time_input.value.strip())
            if minutes <= 0:
                raise ValueError()
        except ValueError:
            await interaction.response.send_message("❌ Entrez un nombre de minutes valide.", ephemeral=True)
            return

        state = get_perms_state()
        current_time = time.time()
        
        if state.get("cm_expire_at", 0) > current_time:
            new_expire = state["cm_expire_at"] + (minutes * 60)
        else:
            new_expire = current_time + (minutes * 60)

        state["cm_expire_at"] = new_expire
        set_perms_state(state)

        log_channel = interaction.client.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed_log = discord.Embed(
                title="⚙️ Temps CM Ajouté",
                description=f"👤 **Par :** {interaction.user.mention}\n➕ **Temps ajouté :** `{minutes}` min\n⏳ **Nouvelle expiration :** <t:{int(new_expire)}:R>",
                color=discord.Color.blue()
            )
            await log_channel.send(embed=embed_log)

        embed = discord.Embed(
            title="✅ Accès CM Mis à Jour",
            description=f"**{minutes} minute(s)** ont été ajoutées pour le rôle <@&{ROLE_CM}>.\n⏳ **Expiration totale :** <t:{int(new_expire)}:R> (<t:{int(new_expire)}:t>).",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class CmActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Ajouter du temps", style=discord.ButtonStyle.primary, emoji="⏱️", custom_id="btn_add_time_cm")
    async def add_time_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_owner_user(interaction):
            await interaction.response.send_message("❌ Réservé au rôle Owner.", ephemeral=True)
            return
        await interaction.response.send_modal(CmTimeModal())

    @discord.ui.button(label="❌ Annuler le temps / Couper l'accès", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="btn_remove_access_cm")
    async def remove_access_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_owner_user(interaction):
            await interaction.response.send_message("❌ Réservé au rôle Owner.", ephemeral=True)
            return

        state = get_perms_state()
        state["cm_expire_at"] = 0
        set_perms_state(state)

        log_channel = interaction.client.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed_log = discord.Embed(
                title="🔒 Temps CM Annulé & Accès Révoqué",
                description=f"👤 **Par :** {interaction.user.mention}\n❌ Le temps restant a été annulé et l'accès au `/gen` pour les CM a été coupé.",
                color=discord.Color.red()
            )
            await log_channel.send(embed=embed_log)

        await interaction.response.send_message("🔒 **Temps CM annulé avec succès.** L'accès au `/gen` est de nouveau fermé pour le rôle CM.", ephemeral=True)


# --- VUES DE GÉNÉRATION DE COMPTE ---
class AccountCopyView(discord.ui.View):
    def __init__(self, service_name: str, email: str, password: str, full_line: str, lines_left: int):
        super().__init__(timeout=180)
        self.service_name = service_name
        self.email = email
        self.password = password
        self.full_line = full_line
        self.lines_left = lines_left

    @discord.ui.button(label="Générer un autre", style=discord.ButtonStyle.success, emoji="➡️", custom_id="gen_next")
    async def next_account(self, interaction: discord.Interaction, button: discord.ui.Button):
        if isinstance(interaction.user, discord.Member) and not can_user_gen(interaction.user):
            await send_no_permission_response(interaction)
            return

        filename = f"stock_{self.service_name}.txt"
        if not os.path.exists(filename):
            await interaction.response.edit_message(content="❌ Stock introuvable.", embed=None, view=None)
            return

        with open(filename, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip() and ":" in line]

        if not lines:
            await interaction.response.edit_message(content="❌ Stock épuisé !", embed=None, view=None)
            await update_live_stock(interaction.client)
            return

        current_time = time.time()
        if not is_owner_user(interaction):
            last_gen = gen_cooldowns.get(interaction.user.id, 0)
            if current_time - last_gen < COOLDOWN_SECONDS:
                remaining = int(COOLDOWN_SECONDS - (current_time - last_gen))
                await interaction.response.send_message(f"⏳ Veuillez patienter **{remaining} seconde(s)** avant de générer un autre compte.", ephemeral=True)
                return
            gen_cooldowns[interaction.user.id] = current_time

        new_account = lines[0]
        separator_index = new_account.find(":")
        new_email = new_account[:separator_index]
        new_pass = new_account[separator_index + 1:]

        with open(filename, "w", encoding="utf-8") as f:
            for line in lines[1:]:
                f.write(line + "\n")

        increment_gen_stat(interaction.user.id)
        await update_live_leaderboard(interaction.client)

        remaining_count = len(lines) - 1
        if remaining_count % 500 == 0 or remaining_count == 0:
            await update_live_stock(interaction.client)

        if self.service_name == "starpets": display_name = "StarPets"
        elif self.service_name == "basicfit": display_name = "Basic-Fit"
        elif self.service_name == "riotgames": display_name = "Riot Games"
        elif self.service_name == "onoff": display_name = "On/Off"
        elif self.service_name == "mulvaldvpn": display_name = "Mulvald VPN"
        else: display_name = self.service_name.capitalize()

        embed = discord.Embed(
            title=f"🎁 Compte {display_name} Généré !",
            description="Voici vos identifiants :",
            color=discord.Color.from_rgb(88, 101, 242)
        )
        embed.add_field(name="📧 Email", value=f"```text\n{new_email}\n```", inline=False)
        embed.add_field(name="🔑 Mot de passe", value=f"```text\n{new_pass}\n```", inline=False)
        embed.set_footer(text=f"Stock restant : {remaining_count} comptes")
        
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.danger, emoji="✖️", custom_id="gen_close")
    async def close_view(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()

class GenSelect(discord.ui.Select):
    def __init__(self):
        options = []
        
        service_emojis = {
            "eldorado": "🛒",
            "eneba": "🎮",
            "epicgames": "🎯",
            "xbox": "💚",
            "hotmail": "📧",
            "crunchyroll": "🟠",
            "start": "⭐",
            "starpets": "🐾",
            "roblox": "🟥",
            "instantgaming": "⚡",
            "steam": "💙",
            "basicfit": "🏋️‍♂️",
            "riotgames": "⚔️",
            "onoff": "📱",
            "mulvaldvpn": "🔒"
        }

        for service in ALL_SERVICES:
            filename = f"stock_{service}.txt"
            count = 0
            if os.path.exists(filename):
                with open(filename, "r", encoding="utf-8") as f:
                    count = sum(1 for line in f if line.strip() and ":" in line)
            
            if service == "epicgames": formatted_name = "Epic Games"
            elif service == "instantgaming": formatted_name = "Instant Gaming"
            elif service == "starpets": formatted_name = "StarPets"
            elif service == "basicfit": formatted_name = "Basic-Fit"
            elif service == "riotgames": formatted_name = "Riot Games"
            elif service == "onoff": formatted_name = "On/Off"
            elif service == "mulvaldvpn": formatted_name = "Mulvald VPN"
            else: formatted_name = service.capitalize()

            emoji = service_emojis.get(service, "📦")
            options.append(discord.SelectOption(label=f"{formatted_name} ({count} dispo)", value=service, emoji=emoji))

        super().__init__(placeholder="💎 Sélectionnez le service...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if isinstance(interaction.user, discord.Member) and not can_user_gen(interaction.user):
            await send_no_permission_response(interaction)
            return

        service_name = self.values[0]
        filename = f"stock_{service_name}.txt"

        if not os.path.exists(filename):
            await interaction.response.send_message("❌ Stock introuvable.", ephemeral=True)
            return

        with open(filename, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip() and ":" in line]

        if not lines:
            await interaction.response.send_message("❌ Stock vide !", ephemeral=True)
            await update_live_stock(interaction.client)
            return

        current_time = time.time()
        if not is_owner_user(interaction):
            last_gen = gen_cooldowns.get(interaction.user.id, 0)
            if current_time - last_gen < COOLDOWN_SECONDS:
                remaining = int(COOLDOWN_SECONDS - (current_time - last_gen))
                await interaction.response.send_message(f"⏳ Veuillez patienter **{remaining} seconde(s)** avant de générer un autre compte.", ephemeral=True)
                return
            gen_cooldowns[interaction.user.id] = current_time

        account = lines[0]
        separator_index = account.find(":")
        email = account[:separator_index]
        password = account[separator_index + 1:]

        with open(filename, "w", encoding="utf-8") as f:
            for line in lines[1:]:
                f.write(line + "\n")

        increment_gen_stat(interaction.user.id)
        await update_live_leaderboard(interaction.client)

        remaining_count = len(lines) - 1
        if remaining_count % 500 == 0 or remaining_count == 0:
            await update_live_stock(interaction.client)

        if service_name == "starpets": display_name = "StarPets"
        elif service_name == "basicfit": display_name = "Basic-Fit"
        elif service_name == "riotgames": display_name = "Riot Games"
        elif service_name == "onoff": display_name = "On/Off"
        elif service_name == "mulvaldvpn": display_name = "Mulvald VPN"
        else: display_name = service_name.capitalize()

        embed = discord.Embed(
            title=f"🎁 Compte {display_name} Généré !",
            description="Voici vos identifiants :",
            color=discord.Color.from_rgb(88, 101, 242)
        )
        embed.add_field(name="📧 Email", value=f"```text\n{email}\n```", inline=False)
        embed.add_field(name="🔑 Mot de passe", value=f"```text\n{password}\n```", inline=False)
        embed.set_footer(text=f"Stock restant : {remaining_count} comptes")

        view = AccountCopyView(service_name, email, password, account, remaining_count)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class GenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GenSelect())


# --- TUTORIEL /GEN ---
def build_tuto_pages() -> list:
    color = discord.Color.from_rgb(88, 101, 242)
    pages = []

    pages.append(discord.Embed(
        title="🎯｜𝘁𝘂𝘁𝗼-𝗴𝗲𝗻  •  Bienvenue !",
        description=(
            f"Ce guide t'explique **pas à pas** comment récupérer ton compte avec la commande `/gen`.\n\n"
            "⏱️ **Ça prend moins d'une minute !**\n\n"
            "**📋 Ce qu'il te faut :**\n"
            f"• Le rôle <@&{ROLE_ACHETEUR}> (donné après ton achat)\n"
            "• Un salon où tu peux écrire des messages\n\n"
            "**🗺️ Le programme :**\n"
            "1️⃣ Lancer la commande\n"
            "2️⃣ Choisir ton service\n"
            "3️⃣ Récupérer tes identifiants\n"
            "4️⃣ Utiliser les boutons\n\n"
            "👉 Clique sur **Suivant ➡️** pour commencer !"
        ),
        color=color
    ))

    pages.append(discord.Embed(
        title="1️⃣  ÉTAPE 1  •  Lancer la commande",
        description=(
            "Dans la **barre de message** en bas de Discord :\n\n"
            "**➊** Tape `/gen`\n"
            "**➋** Discord affiche la commande au-dessus de la barre → **clique dessus** (ou appuie sur `Tab`)\n"
            "**➌** Appuie sur **Entrée** pour l'envoyer\n\n"
            "📱 **Sur mobile :** tape `/`, puis appuie sur **gen** dans la liste qui apparaît.\n\n"
            "⚠️ **Astuce :** ne copie-colle pas `/gen` comme du texte. Il faut **sélectionner la commande dans la liste** "
            "(elle s'affiche avec l'icône du bot), sinon rien ne se passe."
        ),
        color=color
    ))

    pages.append(discord.Embed(
        title="2️⃣  ÉTAPE 2  •  Choisir ton service",
        description=(
            "Un menu apparaît :\n"
            "```\n💎 Sélectionnez le service...\n```\n"
            "**➊** Clique sur le menu déroulant\n"
            "**➋** Repère le nombre entre parenthèses : c'est le stock. Exemple : `Steam (12 dispo)`\n"
            "**➌** Clique sur le service que tu veux\n\n"
            "✅ `(12 dispo)` → des comptes sont disponibles\n"
            "🔴 `(0 dispo)` → plus de stock pour l'instant : choisis un autre service ou attends un restock\n\n"
            f"📦 Tu peux suivre le stock en direct dans <#{STOCK_CHANNEL_ID}>."
        ),
        color=color
    ))

    pages.append(discord.Embed(
        title="3️⃣  ÉTAPE 3  •  Récupérer tes identifiants",
        description=(
            "Ton compte s'affiche **instantanément**, comme ceci :\n\n"
            "**🎁 Compte Steam Généré !**\n"
            "📧 **Email**\n```text\nexemple@mail.com\n```\n"
            "🔑 **Mot de passe**\n```text\nmotdepasse123\n```\n"
            "📋 **Pour copier :**\n"
            "• **PC :** passe la souris sur le cadre gris et clique sur l'icône de copie (ou sélectionne le texte)\n"
            "• **Mobile :** appuie longuement sur le texte, puis « Copier »\n\n"
            "⚠️ **Important :** ce message est **éphémère** (visible que par toi) et disparaît si tu fermes ou "
            "relances Discord. **Copie tes identifiants tout de suite !**"
        ),
        color=color
    ))

    pages.append(discord.Embed(
        title="4️⃣  ÉTAPE 4  •  Les boutons",
        description=(
            "Sous ton compte, tu as deux boutons :\n\n"
            "➡️ **Générer un autre**\n"
            "Te donne un nouveau compte du **même service**.\n"
            "⚠️ Il **remplace** celui affiché : copie le précédent avant de cliquer !\n\n"
            "✖️ **Fermer**\n"
            "Ferme la fenêtre quand tu as terminé.\n\n"
            "⏳ Les boutons restent actifs **3 minutes**. Passé ce délai, refais simplement `/gen`.\n\n"
            "💡 Pour changer de service, relance `/gen` et choisis-en un autre."
        ),
        color=color
    ))

    pages.append(discord.Embed(
        title="❓  Un souci ? Solutions rapides",
        description=(
            "❌ **« Vous n'avez pas l'autorisation d'utiliser /gen »**\n"
            f"→ Il te manque le rôle <@&{ROLE_ACHETEUR}>, ou l'accès est temporairement fermé. Contacte le staff.\n\n"
            "❌ **« Stock vide » / « Stock épuisé »**\n"
            f"→ Le service n'a plus de comptes. Attends le prochain restock : il sera annoncé dans <#{STOCK_CHANNEL_ID}>.\n\n"
            "❌ **« L'interaction a échoué » / le menu ne répond pas**\n"
            f"→ Relance `/gen` et réessaie.\n\n"
            "❌ **La commande `/gen` n'apparaît pas**\n"
            "→ Vérifie que tu es bien sur le serveur et que tu la sélectionnes dans la liste (pas en texte simple).\n\n"
            f"💡 Tu veux un autre service ? Propose-le dans <#{SUGGESTION_CHANNEL_ID}> !\n\n"
            "🎉 **Tu es prêt(e), bonne utilisation !**"
        ),
        color=discord.Color.green()
    ))

    total = len(pages)
    for i, page in enumerate(pages, start=1):
        page.set_footer(text=f"📖 Page {i}/{total} • Tutoriel /gen")

    return pages


class TutoGenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.pages = build_tuto_pages()
        self.index = 0
        self.interaction = None
        self.refresh_buttons()

    def refresh_buttons(self):
        self.prev_page.disabled = (self.index == 0)
        self.next_page.disabled = (self.index == len(self.pages) - 1)

    @discord.ui.button(label="Précédent", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self.refresh_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Suivant", style=discord.ButtonStyle.primary, emoji="➡️")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self.refresh_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.danger, emoji="✖️")
    async def close_tuto(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            content=f"✅ Tutoriel fermé. Tape `/gen` quand tu es prêt(e) !",
            embed=None,
            view=None
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.interaction:
            try:
                await self.interaction.edit_original_response(view=self)
            except discord.HTTPException:
                pass


# --- CONFIGURATION DU BOT & COMMANDES SLASH ---
class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.copy_global_to(guild=GUILD_ID)
        await self.tree.sync(guild=GUILD_ID)
        print("Commandes synchronisées !")

bot = MyBot()

@bot.event
async def on_ready():
    print(f"Connecté avec succès en tant que {bot.user} !")
    bot.loop.create_task(background_leaderboard_update())

async def background_leaderboard_update():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await update_live_leaderboard(bot)
        await asyncio.sleep(60)

@bot.tree.command(name="gen", description="Générer un compte sur l'un de nos services disponibles")
async def slash_gen(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚙️｜𝗴𝗲𝗻-𝗮𝗰𝗰𝗼𝘂𝗻𝘁",
        description="Sélectionnez le service de votre choix dans le menu déroulant ci-dessous pour générer un compte instantanément.",
        color=discord.Color.from_rgb(88, 101, 242)
    )
    view = GenView()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

@bot.tree.command(name="leaderboard", description="Afficher le classement des membres qui ont le plus généré")
async def slash_leaderboard(interaction: discord.Interaction):
    stats = load_json_file(STATS_FILE)
    sorted_stats = sorted(stats.items(), key=lambda item: item[1], reverse=True)[:10]

    embed = discord.Embed(
        title="🏆 ─── [ CLASSEMENT DES GÉNÉRATIONS ] ─── 🏆",
        description="Voici le top 10 des membres ayant généré le plus de comptes !\n\n━━━━━━━━━━━━━━━━━━━━━━",
        color=discord.Color.gold()
    )

    if not sorted_stats:
        embed.add_field(name="📊 Top Membres", value="*Aucune génération enregistrée pour le moment.*", inline=False)
    else:
        lb_lines = []
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for index, (user_id_str, count) in enumerate(sorted_stats):
            medal = medals[index] if index < len(medals) else f"`{index+1}.`"
            lb_lines.append(f"{medal} <@{user_id_str}> ➔ **{count}** génération(s)")
        
        embed.add_field(name="📊 **TOP 10 DES GENS**", value="\n".join(lb_lines), inline=False)

    embed.set_footer(text="✨ Système de stats officiel", icon_url="https://cdn-icons-png.flaticon.com/512/3112/3112946.png")
    await interaction.response.send_message(embed=embed, ephemeral=False)

@bot.tree.command(name="statsgen", description="Voir combien de comptes un membre a générés")
@app_commands.describe(pseaudodumec="Le membre dont vous voulez voir les stats")
async def slash_statsgen(interaction: discord.Interaction, pseaudodumec: discord.Member):
    stats = load_json_file(STATS_FILE)
    user_str = str(pseaudodumec.id)
    count = stats.get(user_str, 0)

    embed = discord.Embed(
        title="📊 Statistiques de Génération",
        description=f"Le membre {pseaudodumec.mention} a généré un total de **{count}** compte(s).",
        color=discord.Color.from_rgb(88, 101, 242)
    )
    embed.set_thumbnail(url=pseaudodumec.display_avatar.url)
    await interaction.response.send_message(embed=embed, ephemeral=False)

@bot.tree.command(name="cooldown", description="Modifier le temps de cooldown de la commande /gen")
@app_commands.describe(lechiffre="Le nombre de secondes de cooldown")
async def slash_cooldown(interaction: discord.Interaction, lechiffre: int):
    global COOLDOWN_SECONDS
    if not is_owner_user(interaction):
        await interaction.response.send_message("❌ Réservé aux administrateurs.", ephemeral=True)
        return

    if lechiffre < 0:
        await interaction.response.send_message("❌ Le cooldown ne peut pas être négatif.", ephemeral=True)
        return

    COOLDOWN_SECONDS = lechiffre

    log_channel = interaction.client.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed_log = discord.Embed(
            title="⏱️ Cooldown Modifié",
            description=f"👤 **Par :** {interaction.user.mention}\n⏱️ **Nouveau cooldown :** `{lechiffre}` seconde(s)",
            color=discord.Color.blue()
        )
        await log_channel.send(embed=embed_log)

    await interaction.response.send_message(f"✅ Le cooldown de la commande `/gen` a été réglé à **{lechiffre}** seconde(s).", ephemeral=True)

@bot.tree.command(name="restock", description="Ajouter un fichier texte pour restock automatiquement un service")
@app_commands.describe(
    service="Le service à restock",
    fichier="Glisse ton fichier .txt contenant les comptes (user:pass)"
)
@app_commands.choices(service=[
    app_commands.Choice(name="Eldorado", value="eldorado"),
    app_commands.Choice(name="Eneba", value="eneba"),
    app_commands.Choice(name="Epic Games", value="epicgames"),
    app_commands.Choice(name="Xbox", value="xbox"),
    app_commands.Choice(name="Hotmail", value="hotmail"),
    app_commands.Choice(name="Crunchyroll", value="crunchyroll"),
    app_commands.Choice(name="Start", value="start"),
    app_commands.Choice(name="StarPets", value="starpets"),
    app_commands.Choice(name="Roblox", value="roblox"),
    app_commands.Choice(name="Instant Gaming", value="instantgaming"),
    app_commands.Choice(name="Steam", value="steam"),
    app_commands.Choice(name="Basic-Fit", value="basicfit"),
    app_commands.Choice(name="Riot Games", value="riotgames"),
    app_commands.Choice(name="On/Off", value="onoff"),
    app_commands.Choice(name="Mulvald VPN", value="mulvaldvpn"),
])
async def slash_restock(interaction: discord.Interaction, service: str, fichier: discord.Attachment):
    if not is_owner_user(interaction):
        await interaction.response.send_message("❌ Réservé aux administrateurs.", ephemeral=True)
        return

    if not fichier.filename.endswith(".txt"):
        await interaction.response.send_message("❌ Le fichier doit obligatoirement être au format `.txt`.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    try:
        file_bytes = await fichier.read()
        content = file_bytes.decode("utf-8", errors="ignore")
    except Exception as e:
        await interaction.followup.send(f"❌ Erreur lors de la lecture du fichier : {e}", ephemeral=True)
        return

    lines = [line.strip() for line in content.splitlines() if ":" in line and line.strip()]

    if not lines:
        await interaction.followup.send("❌ Aucun compte valide (format `user:pass`) trouvé dans ce fichier.", ephemeral=True)
        return

    filename = f"stock_{service}.txt"
    with open(filename, "a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")

    with open(filename, "r", encoding="utf-8") as f:
        total_stock = sum(1 for line in f if line.strip() and ":" in line)

    if service == "starpets": formatted_name = "StarPets"
    elif service == "epicgames": formatted_name = "Epic Games"
    elif service == "instantgaming": formatted_name = "Instant Gaming"
    elif service == "basicfit": formatted_name = "Basic-Fit"
    elif service == "riotgames": formatted_name = "Riot Games"
    elif service == "onoff": formatted_name = "On/Off"
    elif service == "mulvaldvpn": formatted_name = "Mulvald VPN"
    else: formatted_name = service.capitalize()

    acheteur_channel = interaction.client.get_channel(ACHETEUR_NOTIF_CHANNEL_ID)
    if acheteur_channel:
        await acheteur_channel.send(f"🎉 **Du nouveau stock est disponible !** Le service **{formatted_name}** a été restocké avec **{len(lines)}** nouveaux comptes. Stock total : **{total_stock}**.")

    log_channel = interaction.client.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed_log = discord.Embed(
            title="📥 Nouveau Restock Enregistré (Via TXT)",
            description=f"👤 **Par :** {interaction.user.mention}\n📦 **Service :** `{formatted_name}`\n➕ **Ajoutés :** `{len(lines)}`\n📈 **Total :** `{total_stock}`",
            color=discord.Color.green()
        )
        await log_channel.send(embed=embed_log)

    await update_live_stock(interaction.client)

    embed = discord.Embed(
        title="✅ Restock Réussi !",
        description=f"Service : **{formatted_name}**\nComptes ajoutés : `{len(lines)}`\n📦 Stock total : `{total_stock}`",
        color=discord.Color.green()
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="delstock", description="Supprimer un certain nombre de comptes d'un service")
@app_commands.describe(
    service="Le service dont il faut retirer des comptes",
    nombre="Nombre de comptes à supprimer du haut du stock"
)
@app_commands.choices(service=[
    app_commands.Choice(name="Eldorado", value="eldorado"),
    app_commands.Choice(name="Eneba", value="eneba"),
    app_commands.Choice(name="Epic Games", value="epicgames"),
    app_commands.Choice(name="Xbox", value="xbox"),
    app_commands.Choice(name="Hotmail", value="hotmail"),
    app_commands.Choice(name="Crunchyroll", value="crunchyroll"),
    app_commands.Choice(name="Start", value="start"),
    app_commands.Choice(name="StarPets", value="starpets"),
    app_commands.Choice(name="Roblox", value="roblox"),
    app_commands.Choice(name="Instant Gaming", value="instantgaming"),
    app_commands.Choice(name="Steam", value="steam"),
    app_commands.Choice(name="Basic-Fit", value="basicfit"),
    app_commands.Choice(name="Riot Games", value="riotgames"),
    app_commands.Choice(name="On/Off", value="onoff"),
    app_commands.Choice(name="Mulvald VPN", value="mulvaldvpn"),
])
async def slash_delstock(interaction: discord.Interaction, service: str, nombre: int = 1):
    if not is_owner_user(interaction):
        await interaction.response.send_message("❌ Réservé aux administrateurs.", ephemeral=True)
        return

    if nombre <= 0:
        await interaction.response.send_message("❌ Le nombre de comptes à supprimer doit être supérieur à 0.", ephemeral=True)
        return

    filename = f"stock_{service}.txt"
    if not os.path.exists(filename):
        await interaction.response.send_message("❌ Le fichier de stock pour ce service n'existe pas.", ephemeral=True)
        return

    with open(filename, "r", encoding="utf-8") as f:
        stock = [line.strip() for line in f.readlines() if line.strip() and ":" in line]

    if len(stock) < nombre:
        await interaction.response.send_message(f"❌ Il n'y a pas assez de comptes dans le stock (Stock actuel : {len(stock)}).", ephemeral=True)
        return

    stock = stock[nombre:]
    with open(filename, "w", encoding="utf-8") as f:
        for line in stock:
            f.write(line + "\n")

    if service == "starpets": formatted_name = "StarPets"
    elif service == "epicgames": formatted_name = "Epic Games"
    elif service == "instantgaming": formatted_name = "Instant Gaming"
    elif service == "basicfit": formatted_name = "Basic-Fit"
    elif service == "riotgames": formatted_name = "Riot Games"
    elif service == "onoff": formatted_name = "On/Off"
    elif service == "mulvaldvpn": formatted_name = "Mulvald VPN"
    else: formatted_name = service.capitalize()

    await update_live_stock(interaction.client)

    await interaction.response.send_message(f"✅ **{nombre}** compte(s) ont été supprimés du service **{formatted_name}**. Stock restant : **{len(stock)}**", ephemeral=True)

@bot.tree.command(name="panel_cm", description="Afficher le panneau de gestion du temps CM")
async def slash_panel_cm(interaction: discord.Interaction):
    if not is_owner_user(interaction):
        await interaction.response.send_message("❌ Réservé aux administrateurs.", ephemeral=True)
        return

    embed = discord.Embed(
        title="⏱️ Gestion de l'accès CM",
        description="Utilisez les boutons ci-dessous pour ajouter du temps ou annuler/couper immédiatement l'accès au `/gen` pour les CM.",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, view=CmActionView(), ephemeral=True)

@bot.tree.command(name="tuto_gen", description="Tutoriel pas à pas pour apprendre à utiliser /gen")
async def slash_tuto_gen(interaction: discord.Interaction):
    view = TutoGenView()
    await interaction.response.send_message(embed=view.pages[0], view=view, ephemeral=True)
    view.interaction = interaction

if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
