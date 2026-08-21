import os
import discord
from discord import app_commands
from discord.ext import commands

# 1. Set up bot intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 2. Global Data Structures
registered_teams = {}  # {captain_id: {"team_name": X, "players": [id1, id2...]}}
MAX_TEAMS = 8
VALORANT_MAPS = ["Abyss", "Ascent", "Bind", "Haven", "Lotus", "Split", "Sunset"]
active_vetos = {}      # {channel_id: {"team1": id, "team2": id, "banned": [], "turn": id}}


# 3. Persistent Registration System UI (Modal Form & Button)
class TeamRegistrationModal(discord.ui.Modal, title="Valorant Team Registration"):
    team_name = discord.ui.TextInput(label="Team Name", placeholder="Enter your competitive team name...", required=True)
    player2 = discord.ui.TextInput(label="Player 2 Name / Discord Tag", placeholder="e.g. Tenz#NA1 or @User", required=True)
    player3 = discord.ui.TextInput(label="Player 3 Name / Discord Tag", placeholder="e.g. Chronicle#EUW", required=True)
    player4 = discord.ui.TextInput(label="Player 4 Name / Discord Tag", placeholder="e.g. Aspas#BR1", required=True)
    player5 = discord.ui.TextInput(label="Player 5 Name / Discord Tag", placeholder="e.g. Boaster#EUW", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        captain = interaction.user
        
        if len(registered_teams) >= MAX_TEAMS:
            return await interaction.response.send_message("❌ Registration failed: The scrim slots are completely full!", ephemeral=True)

        if captain.id in registered_teams:
            return await interaction.response.send_message("❌ You have already registered a team!", ephemeral=True)

        # Collect roster text strings from inputs
        roster_text = f"1. {captain.mention}\n2. {self.player2.value}\n3. {self.player3.value}\n4. {self.player4.value}\n5. {self.player5.value}"

        # Save team mapping data to memory
        registered_teams[captain.id] = {
            "team_name": self.team_name.value,
            "players": [captain.name, self.player2.value, self.player3.value, self.player4.value, self.player5.value]
        }

        embed = discord.Embed(title="✅ Team Registered Successfully!", color=discord.Color.green())
        embed.add_field(name="Team Name", value=self.team_name.value, inline=False)
        embed.add_field(name="Captain", value=captain.mention, inline=True)
        embed.add_field(name="Slots Taken", value=f"{len(registered_teams)}/{MAX_TEAMS}", inline=True)
        embed.add_field(name="Roster", value=roster_text, inline=False)

        await interaction.response.send_message(embed=embed)


class RegisterButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Keeps button listening indefinitely even after restarts

    @discord.ui.button(label="Register Team", style=discord.ButtonStyle.success, custom_id="persistent_register_button")
    async def register_click(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TeamRegistrationModal())


# 4. Bot Lifecycle Event
@bot.event
async def on_ready():
    # Tell the bot engine to remember the button view layout across restarts
    bot.add_view(RegisterButtonView())
    await bot.tree.sync()
    print(f"Valorant Scrim Bot is online as {bot.user}")


# 5. Admin Registration Setup Panels
@bot.tree.command(name="setup_registration", description="Post the persistent registration panel inside a channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_registration(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏆 Valorant Scrim Sign-Ups",
        description="Click the button below to register your 5-stack roster for tonight's scrim matches!\n\n**Requirements:**\n* Must be the Team Captain clicking.\n* Have your team roster tags ready.",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed, view=RegisterButtonView())


# 6. View All Registered Teams
@bot.tree.command(name="scrim_list", description="Show all teams currently registered for the scrim.")
async def scrim_list(interaction: discord.Interaction):
    if not registered_teams:
        return await interaction.response.send_message("📭 No teams have registered yet! Use the panel button to join.", ephemeral=True)
    
    embed = discord.Embed(title="🏆 Current Valorant Scrim Lobby", color=discord.Color.blue())
    
    for captain_id, data in registered_teams.items():
        # Display index 0 player as the captain object link, rest as flat descriptive names
        roster_text = f"👑 <@{captain_id}>\n" + "\n".join([f"👤 {p}" for p in data["players"][1:]])
        
        embed.add_field(
            name=f"🟢 Team: {data['team_name']}", 
            value=f"{roster_text}", 
            inline=False
        )
        
    await interaction.response.send_message(embed=embed)


# 7. Clear Lobby (Admin Only)
@bot.tree.command(name="scrim_clear", description="Clear all registered teams to start a new scrim session.")
@app_commands.checks.has_permissions(manage_guild=True)
async def scrim_clear(interaction: discord.Interaction):
    global registered_teams
    registered_teams.clear()
    await interaction.response.send_message("🧹 The scrim lobby has been cleared. Registration is reset!")

@scrim_clear.error
async def clear_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You do not have permission to clear the scrim lobby.", ephemeral=True)


# 8. Map Ban Interactive Logic
class MapBanView(discord.ui.View):
    def __init__(self, channel_id, team1_id, team2_id, team1_name, team2_name):
        super().__init__(timeout=300)
        self.channel_id = channel_id
        self.t1_id = team1_id
        self.t2_id = team2_id
        self.t1_name = team1_name
        self.t2_name = team2_name
        self.current_turn = team1_id
        self.banned_maps = []
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        session = active_vetos.get(self.channel_id)
        if not session:
            return

        for map_name in VALORANT_MAPS:
            if map_name in self.banned_maps:
                btn = discord.ui.Button(label=map_name, style=discord.ButtonStyle.danger, disabled=True)
            else:
                btn = discord.ui.Button(label=map_name, style=discord.ButtonStyle.primary, custom_id=map_name)
                btn.callback = self.make_callback(map_name)
            self.add_item(btn)

    def make_callback(self, map_name):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.current_turn:
                return await interaction.response.send_message("❌ It is not your turn to ban a map!", ephemeral=True)

            self.banned_maps.append(map_name)
            active_vetos[self.channel_id]["banned"].append(map_name)
            
            remaining_maps = [m for m in VALORANT_MAPS if m not in self.banned_maps]

            if len(remaining_maps) == 1:
                final_map = remaining_maps[0]
                embed = discord.Embed(
                    title="🎮 Map Veto Complete!",
                    description=f"All maps have been vetoed. You will be playing on:\n\n# 🗺️ **{final_map}**",
                    color=discord.Color.gold()
                )
                active_vetos.pop(self.channel_id, None)
                await interaction.response.edit_message(embed=embed, view=None)
                return

            self.current_turn = self.t2_id if self.current_turn == self.t1_id else self.t1_id
            active_vetos[self.channel_id]["turn"] = self.current_turn
            current_team_name = self.t1_name if self.current_turn == self.t1_id else self.t2_name
            
            self.update_buttons()
            embed = discord.Embed(
                title="🗺️ Valorant Map Pick & Ban",
                description=f"**Current Turn:** <@{self.current_turn}> ({current_team_name})\nClick a button below to **ban** that map.",
                color=discord.Color.orange()
            )
            embed.add_field(name="Banned Maps", value=", ".join(self.banned_maps) if self.banned_maps else "None", inline=False)
            
            await interaction.response.edit_message(embed=embed, view=self)

        return callback


# 9. Map Ban Command Trigger
@bot.tree.command(name="mapban", description="Start a map veto between two registered captains.")
@app_commands.describe(captain1="The first team's captain", captain2="The second team's captain")
async def mapban(interaction: discord.Interaction, captain1: discord.Member, captain2: discord.Member):
    if captain1.id not in registered_teams or captain2.id not in registered_teams:
        return await interaction.response.send_message("❌ Error: Both users must be registered team captains. Use `/scrim_list` to check.", ephemeral=True)

    t1_name = registered_teams[captain1.id]["team_name"]
    t2_name = registered_teams[captain2.id]["team_name"]

    active_vetos[interaction.channel_id] = {
        "team1": captain1.id,
        "team2": captain2.id,
        "banned": [],
        "turn": captain1.id
    }

    embed = discord.Embed(
        title="🗺️ Valorant Map Pick & Ban",
        description=f"**{t1_name}** vs **{t2_name}**\n\n**Current Turn:** {captain1.mention} to ban first.",
        color=discord.Color.orange()
    )
    
    view = MapBanView(interaction.channel_id, captain1.id, captain2.id, t1_name, t2_name)
    await interaction.response.send_message(embed=embed, view=view)


# 10. Start the Runtime Environment Engine
bot.run(os.environ.get("DISCORD_TOKEN"))
