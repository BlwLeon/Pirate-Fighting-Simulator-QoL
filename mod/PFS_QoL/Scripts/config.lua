-- ============================================================
--  PFS QoL Helper – settings
--  The launcher edits the lines marked [launcher]. You can also
--  edit this file by hand; restart the game afterwards.
-- ============================================================
return {
    -- [launcher] Fair-play lock: the helper only turns on when EVERY
    -- player in the lobby (including the host) runs it. Detected via
    -- the name tag below. false = always on (unfair in public lobbies!)
    REQUIRE_ALL_PLAYERS = true,

    -- Appended to your player name so other helpers can see you use it.
    NAME_TAG = " [QoL]",

    -- [launcher] In-game language: "de" or "en"
    LANGUAGE = "de",

    -- [launcher] Hotkeys (UE4SS key names, e.g. Key.F6, Key.INS, Key.NUM_ZERO)
    KEY_TOGGLE = Key.F6,   -- overlay on/off
    KEY_DUMP   = Key.F7,   -- debug dump into UE4SS.log

    -- Features
    SHOW_CROSSHAIR  = true,
    SHOW_HP         = true,
    SHOW_KILL_INFO  = true,   -- own kill feed with distance + HP left
    SHOW_DEATH_INFO = true,   -- big notice when YOU die
    SHOW_STREAK     = true,   -- victim's ended kill streak
    SHOW_BANANAS    = true,   -- bananas the victim ate in that life

    -- Crosshair
    CROSSHAIR_TEXT  = "+",
    CROSSHAIR_SIZE  = 26,
    CROSSHAIR_COLOR = { R = 1.0, G = 1.0, B = 1.0, A = 0.9 },

    -- HP display (offset from the bottom-left corner)
    HP_SIZE   = 28,
    HP_POS    = { X = 40, Y = -140 },

    -- Own kill feed (offset from the top-right corner)
    FEED_SIZE    = 16,
    FEED_POS     = { X = -30, Y = 260 },
    FEED_LINES   = 5,
    FEED_SECONDS = 8,

    -- The host shares killer, HP left and bananas with all clients
    -- (via the unused replicated fields Score / StartTime).
    SHARE_KILL_HP = true,

    -- Override if auto-detection of the health variable fails
    HEALTH_PROPERTY     = nil,
    MAX_HEALTH_PROPERTY = nil,

    -- Unreal units are centimetres -> /100 = metres
    UNITS_PER_METER = 100,
}
