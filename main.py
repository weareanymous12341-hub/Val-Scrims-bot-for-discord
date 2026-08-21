const {
  Client,
  GatewayIntentBits,
  Partials,
  Events,
  REST,
  Routes,
  SlashCommandBuilder,
  PermissionFlagsBits,
  EmbedBuilder,
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
} = require("discord.js");

// 1. Set up bot intents
const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMembers,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
  ],
  partials: [Partials.Channel],
});

// 2. Global Data Structures
const registeredTeams = new Map(); // captainId -> { teamName, players: [id1, id2, ...] }
const MAX_TEAMS = 8;
const VALORANT_MAPS = ["Abyss", "Ascent", "Bind", "Haven", "Lotus", "Split", "Sunset"];
const activeVetos = new Map(); // channelId -> { team1, team2, team1Name, team2Name, banned: [], turn }

// ---- Slash command definitions ----
const commands = [
  new SlashCommandBuilder()
    .setName("register")
    .setDescription("Register your 5-stack Valorant team for the scrim.")
    .addStringOption((opt) =>
      opt.setName("team_name").setDescription("The name of your competitive team").setRequired(true)
    )
    .addUserOption((opt) =>
      opt.setName("player2").setDescription("Mention your second player").setRequired(true)
    )
    .addUserOption((opt) =>
      opt.setName("player3").setDescription("Mention your third player").setRequired(true)
    )
    .addUserOption((opt) =>
      opt.setName("player4").setDescription("Mention your fourth player").setRequired(true)
    )
    .addUserOption((opt) =>
      opt.setName("player5").setDescription("Mention your fifth player").setRequired(true)
    ),

  new SlashCommandBuilder()
    .setName("scrim_list")
    .setDescription("Show all teams currently registered for the scrim."),

  new SlashCommandBuilder()
    .setName("scrim_clear")
    .setDescription("Clear all registered teams to start a new scrim session.")
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild),

  new SlashCommandBuilder()
    .setName("mapban")
    .setDescription("Start a map veto between two registered captains.")
    .addUserOption((opt) =>
      opt.setName("captain1").setDescription("The first team's captain").setRequired(true)
    )
    .addUserOption((opt) =>
      opt.setName("captain2").setDescription("The second team's captain").setRequired(true)
    ),
].map((cmd) => cmd.toJSON());

client.once(Events.ClientReady, async (c) => {
  try {
    const rest = new REST({ version: "10" }).setToken(process.env.DISCORD_TOKEN);
    await rest.put(Routes.applicationCommands(c.user.id), { body: commands });
    console.log(`Valorant Scrim Bot is online as ${c.user.tag}`);
  } catch (err) {
    console.error("Failed to sync slash commands:", err);
  }
});

// ---- Helper: build the map-ban button rows (chunked into rows of 5) ----
function buildMapBanComponents(bannedMaps) {
  const buttons = VALORANT_MAPS.map((mapName) => {
    const isBanned = bannedMaps.includes(mapName);
    return new ButtonBuilder()
      .setCustomId(`mapban_${mapName}`)
      .setLabel(mapName)
      .setStyle(isBanned ? ButtonStyle.Danger : ButtonStyle.Primary)
      .setDisabled(isBanned);
  });

  const rows = [];
  for (let i = 0; i < buttons.length; i += 5) {
    rows.push(new ActionRowBuilder().addComponents(buttons.slice(i, i + 5)));
  }
  return rows;
}

// ---- Interaction handling ----
client.on(Events.InteractionCreate, async (interaction) => {
  // Slash commands
  if (interaction.isChatInputCommand()) {
    const { commandName } = interaction;

    // 3. Registration Slash Command
    if (commandName === "register") {
      const captain = interaction.user;
      const teamName = interaction.options.getString("team_name");
      const player2 = interaction.options.getMember("player2");
      const player3 = interaction.options.getMember("player3");
      const player4 = interaction.options.getMember("player4");
      const player5 = interaction.options.getMember("player5");

      if (registeredTeams.size >= MAX_TEAMS) {
        return interaction.reply({
          content: "❌ Registration failed: The scrim slots are completely full!",
          ephemeral: true,
        });
      }

      if (registeredTeams.has(captain.id)) {
        return interaction.reply({
          content: "❌ You have already registered a team!",
          ephemeral: true,
        });
      }

      const teamMembers = [captain, player2.user, player3.user, player4.user, player5.user];
      const memberIds = teamMembers.map((m) => m.id);

      if (new Set(memberIds).size < 5) {
        return interaction.reply({
          content: "❌ Error: A 5-stack must consist of 5 unique players. You cannot duplicate tags.",
          ephemeral: true,
        });
      }

      registeredTeams.set(captain.id, { teamName, players: memberIds });

      const rosterMentions = teamMembers.map((m) => `<@${m.id}>`).join(", ");

      const embed = new EmbedBuilder()
        .setTitle("✅ Team Registered Successfully!")
        .setColor(0x2ecc71)
        .addFields(
          { name: "Team Name", value: teamName, inline: false },
          { name: "Captain", value: `<@${captain.id}>`, inline: true },
          { name: "Slots Taken", value: `${registeredTeams.size}/${MAX_TEAMS}`, inline: true },
          { name: "Roster", value: rosterMentions, inline: false }
        );

      return interaction.reply({ embeds: [embed] });
    }

    // 4. View All Registered Teams
    if (commandName === "scrim_list") {
      if (registeredTeams.size === 0) {
        return interaction.reply({
          content: "📭 No teams have registered yet! Use `/register` to join.",
          ephemeral: true,
        });
      }

      const embed = new EmbedBuilder().setTitle("🏆 Current Valorant Scrim Lobby").setColor(0x3498db);

      for (const [captainId, data] of registeredTeams.entries()) {
        const rosterText = data.players.map((pid) => `<@${pid}>`).join(", ");
        embed.addFields({
          name: `🟢 Team: ${data.teamName}`,
          value: `**Captain:** <@${captainId}>\n**Roster:** ${rosterText}`,
          inline: false,
        });
      }

      return interaction.reply({ embeds: [embed] });
    }

    // 5. Clear Lobby (Admin Only)
    if (commandName === "scrim_clear") {
      if (!interaction.memberPermissions?.has(PermissionFlagsBits.ManageGuild)) {
        return interaction.reply({
          content: "❌ You do not have permission to clear the scrim lobby.",
          ephemeral: true,
        });
      }

      registeredTeams.clear();
      return interaction.reply("🧹 The scrim lobby has been cleared. Registration is reset!");
    }

    // 7. Map Ban Activation Slash Command
    if (commandName === "mapban") {
      const captain1 = interaction.options.getUser("captain1");
      const captain2 = interaction.options.getUser("captain2");

      if (!registeredTeams.has(captain1.id) || !registeredTeams.has(captain2.id)) {
        return interaction.reply({
          content: "❌ Error: Both users must be registered team captains. Use `/scrim_list` to check.",
          ephemeral: true,
        });
      }

      const t1Name = registeredTeams.get(captain1.id).teamName;
      const t2Name = registeredTeams.get(captain2.id).teamName;

      activeVetos.set(interaction.channelId, {
        team1: captain1.id,
        team2: captain2.id,
        team1Name: t1Name,
        team2Name: t2Name,
        banned: [],
        turn: captain1.id,
      });

      const embed = new EmbedBuilder()
        .setTitle("🗺️ Valorant Map Pick & Ban")
        .setDescription(
          `**${t1Name}** vs **${t2Name}**\n\n**Current Turn:** <@${captain1.id}> to ban first.`
        )
        .setColor(0xe67e22);

      return interaction.reply({
        embeds: [embed],
        components: buildMapBanComponents([]),
      });
    }

    return;
  }

  // 6. Map Ban Interactive Component Handling
  if (interaction.isButton() && interaction.customId.startsWith("mapban_")) {
    const session = activeVetos.get(interaction.channelId);
    if (!session) {
      return interaction.reply({ content: "❌ There is no active map veto in this channel.", ephemeral: true });
    }

    if (interaction.user.id !== session.turn) {
      return interaction.reply({ content: "❌ It is not your turn to ban a map!", ephemeral: true });
    }

    const mapName = interaction.customId.replace("mapban_", "");
    session.banned.push(mapName);

    const remainingMaps = VALORANT_MAPS.filter((m) => !session.banned.includes(m));

    if (remainingMaps.length === 1) {
      const finalMap = remainingMaps[0];
      const embed = new EmbedBuilder()
        .setTitle("🎮 Map Veto Complete!")
        .setDescription(`All maps have been vetoed. You will be playing on:\n\n# 🗺️ **${finalMap}**`)
        .setColor(0xf1c40f);

      activeVetos.delete(interaction.channelId);
      return interaction.update({ embeds: [embed], components: [] });
    }

    session.turn = session.turn === session.team1 ? session.team2 : session.team1;
    const currentTeamName = session.turn === session.team1 ? session.team1Name : session.team2Name;

    const embed = new EmbedBuilder()
      .setTitle("🗺️ Valorant Map Pick & Ban")
      .setDescription(
        `**Current Turn:** <@${session.turn}> (${currentTeamName})\nClick a button below to **ban** that map.`
      )
      .setColor(0xe67e22)
      .addFields({
        name: "Banned Maps",
        value: session.banned.length ? session.banned.join(", ") : "None",
        inline: false,
      });

    return interaction.update({
      embeds: [embed],
      components: buildMapBanComponents(session.banned),
    });
  }
});

// 8. Fire up the bot (MAKE SURE TO INJECT YOUR TOKEN VIA ENV VAR)
client.login(process.env.DISCORD_TOKEN);
