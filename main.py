import os
import random
import asyncio
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
MAX_TEAMS = 2          # Head-to-head automation trigger
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
            return await interaction.response.send_message("❌ Registration failed: The match slots are already full!", ephemeral=True)

        if captain.id in registered_teams:
            return await interaction.response.send_message("❌ You have already registered a team!", ephemeral=True)

        # Save team data to memory
        registered_teams[captain.id] = {
            "team_name": self.team_name.value,
            "players": [captain.name, self.player2.value, self.player3.value, self.player4.value, self.player5.value]
        }

        await interaction.response.send_message(f"✅ Your team **{self.team_name.value}** has been recorded!", ephemeral=True)

        # 🚀 AUTOMATION TRIGGER CHECK
        if len(registered_teams) == MAX_TEAMS:
            closed_embed = discord.Embed(
                title="🏆 Valorant Scrim Sign-Ups [CLOSED]",
                description="Slots are full! The automated BO3 map veto is commencing below.",
                color=discord.Color.dark_grey()
            )
            await interaction.message.edit(embed=closed_embed, view=None)

            # Pull both captain IDs out of memory
            captain_ids = list(registered_teams.keys())
            c1_id, c2_id = captain_ids[0], captain_ids[1]
            
            t1_name = registered_teams[c1_id]["team_name"]
            t2_name = registered_teams[c2_id]["team_name"]

            # Initialize map ban state
            active_vetos[interaction.channel_id] = {
                "team1": c1_id,
                "team2": c2_id,
                "banned": [],
                "turn": c1_id
            }

            veto_embed = discord.Embed(
                title="🗺️ Automated BO3 Map Pick & Ban",
                description=f"⚔️ **{t1_name}** vs **{t2_name}**\n\n**Current Turn:** <@{c1_id}> to ban first.",
                color=discord.Color.orange()
            )
            
            view = MapBanView(interaction.channel_id, c1_id, c2_id, t1_name, t2_name)
            await interaction.channel.send(content=f"<@{c1_id}> <@{c2_id}>: Your match is set! Begin banning until 3 maps remain.", embed=veto_embed, view=view)
            
        else:
            updated_embed = discord.Embed(
                title="🏆 Valorant Scrim Sign-Ups",
                description=f"Click the button below to register!\n\n**Slots Filled:** 1/{MAX_TEAMS}\n**Waiting for Opponent...**",
                color=discord.Color.red()
            )
            await interaction.message.edit(embed=updated_embed, view=RegisterButtonView())


class RegisterButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Register Team", style=discord.ButtonStyle.success, custom_id="persistent_register_button")
    async def register_click(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TeamRegistrationModal())


# 4. Bot Lifecycle Event
@bot.event
async def on_ready():
    bot.add_view(RegisterButtonView())
    await bot.tree.sync()
    print(f"Valorant Scrim Bot is online as {bot.user}")


# 5. Setup Panel Command
@bot.tree.command(name="setup_registration", description="Post the persistent registration panel inside a channel.")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_registration(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏆 Valorant Scrim Sign-Ups",
        description=f"Click the button below to register your 5-stack roster for the next match!\n\n**Slots Filled:** 0/{MAX_TEAMS}",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed, view=RegisterButtonView())


# 6. Clear Match/Lobby (Admin Reset)
@bot.tree.command(name="scrim_clear", description="Reset registration panel and clear memory.")
@app_commands.checks.has_permissions(manage_guild=True)
async def scrim_clear(interaction: discord.Interaction):
    global registered_teams
    registered_teams.clear()
    
    embed = discord.Embed(
        title="🏆 Valorant Scrim Sign-Ups",
        description=f"The lobby has been reset by an admin!\n\nClick below to register.\n**Slots Filled:** 0/{MAX_TEAMS}",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed, view=RegisterButtonView())


# 7. Map Ban Interactive UI Components (BO3 Roll Edition)
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

            # Stop when exactly 3 maps are left
            if len(remaining_maps) == 3:
                active_vetos.pop(self.channel_id, None)

                roll_embed = discord.Embed(
                    title="🎲 Veto Complete! Rolling Starting Map...",
                    description="Choosing which map will be played first from the pool:\n" + ", ".join([f"`{m}`" for m in remaining_maps]),
                    color=discord.Color.purple()
                )
                await interaction.response.edit_message(embed=roll_embed, view=None)

                await asyncio.sleep(2.5)

                random.shuffle(remaining_maps)
                map_1 = remaining_maps[0]
                map_2 = remaining_maps[1]
                map_3 = remaining_maps[2]

                final_embed = discord.Embed(
                    title="🎮 Match Order Locked In!",
                    description="The remaining pool maps have been randomized for the sequence.",
                    color=discord.Color.gold()
                )
                final_embed.add_field(name="🗺️ MAP 1 (Rolled First)", value=f"**{map_1}**", inline=False)
                final_embed.add_field(name="🗺️ MAP 2", value=f"**{map_2}**", inline=True)
                final_embed.add_field(name="🗺️ MAP 3 (If Needed)", value=f"**{map_3}**", inline=True)
                final_embed.set_footer(text="⚔️ BEST OF 3 SERIES")

                await interaction.followup.send(embed=final_embed)
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


# 8. Start the Runtime Environment Engine
bot.run(os.environ.get("DISCORD_TOKEN"))
