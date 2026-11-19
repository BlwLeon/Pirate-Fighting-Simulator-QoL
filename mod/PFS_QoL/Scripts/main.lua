-- ============================================================
--  PFS QoL Helper v2  –  UE4SS Lua Mod für Pirate Fighting Simulator
--  Features: Crosshair, HP als Zahl, Kill-Info (Distanz + Rest-HP)
--  Fairness: nur aktiv, wenn alle Spieler der Lobby den Helper nutzen
-- ============================================================
local cfg = require("config")

local VERSION = "1.0.1"
local TAG = "[PFS_QoL] "

-- ------------------------------------------------------------
--  Texte (config.lua: LANGUAGE = "de" oder "en")
-- ------------------------------------------------------------
local TEXTS = {
    de = {
        status_test   = "QoL %s aktiv (Fair-Play-Sperre aus)",
        status_on     = "QoL aktiv  %d/%d",
        status_off    = "QoL AUS – ohne Helper: %s",
        feed_kill     = "%s  >  %s   %s m   (%s HP übrig)",
        feed_died     = "%s ist gestorben",
        streak        = "beendet %der-Streak",
        banana_one    = "Banane",
        banana_many   = "Bananen",
        death_by      = "Getötet von %s\n%s hatte noch %s HP  ·  Distanz %s m",
        death_self    = "Du bist gestorben",
        your_life     = "Dein Leben: ",
    },
    en = {
        status_test   = "QoL %s active (fair-play lock off)",
        status_on     = "QoL active  %d/%d",
        status_off    = "QoL OFF – players without helper: %s",
        feed_kill     = "%s  >  %s   %s m   (%s HP left)",
        feed_died     = "%s died",
        streak        = "ended a %d streak",
        banana_one    = "banana",
        banana_many   = "bananas",
        death_by      = "Killed by %s\n%s had %s HP left  ·  distance %s m",
        death_self    = "You died",
        your_life     = "Your life: ",
    },
}
local T = TEXTS[(require("config").LANGUAGE or "de")] or TEXTS.de
local function log(...)
    local parts = {}
    for i = 1, select("#", ...) do parts[#parts + 1] = tostring(select(i, ...)) end
    print(TAG .. table.concat(parts, " ") .. "\n")
end

-- pcall, der jeden Fehler nur EINMAL ins Log schreibt (zum Debuggen)
local reported = {}
local function try(label, fn, ...)
    local ok, r = pcall(fn, ...)
    if not ok and not reported[label] then
        reported[label] = true
        log("WARN", label, "->", r)
    end
    if ok then return r end
    return nil
end

local PATH_KILLFEED_ELEMENT = "/Game/KillFeed/Blueprints/UI/UI_KillFeedElement.UI_KillFeedElement_C"
local PATH_KILLED_BY        = "/Game/ThirdPerson/Blueprints/NewGusStuff/WidgetsFolder/KilledBy.KilledBy_C"

-- Bekannte Variablen aus dem Dump (GusPlayer / TrainGusPlayer)
local P_HEALTH        = "Current Health"
local P_CLIENT_HEALTH = "client health"
local P_DEAD1         = "IsDead?"
local P_DEAD2         = "Dead?"
local P_LAST_HIT      = "Last Hit By"
local P_LAST_HIT_NAME = "Last Hit By Name"
local P_DEATH_LOC     = "Death location"
local P_MY_NAME       = "My Name"

local TICK_MS = 50
local now = 0
local enabledByUser = true
local active = false
local statusText = ""

-- ------------------------------------------------------------
--  Hilfsfunktionen
-- ------------------------------------------------------------
local function valid(o)
    if o == nil then return false end
    local ok, r = pcall(function() return o:IsValid() end)
    return ok and r
end

local function str(v)
    if v == nil then return nil end
    local tv = type(v)
    if tv == "string" then return v end
    if tv == "number" or tv == "boolean" then return tostring(v) end
    local ok, r = pcall(function() return v:ToString() end)
    if ok and type(r) == "string" then return r end
    return nil
end

local function prop(o, name)
    local ok, v = pcall(function() return o[name] end)
    if ok then return v end
    return nil
end

local function className(o)
    local ok, r = pcall(function() return o:GetClass():GetFName():ToString() end)
    return ok and r or "?"
end

local function classChainHas(o, needle)
    local ok, r = pcall(function()
        local c = o:GetClass()
        while c and c:IsValid() do
            if c:GetFName():ToString():find(needle, 1, true) then return true end
            c = c:GetSuperStruct()
        end
        return false
    end)
    return ok and r
end

local function forEachProp(o, cb, stopAt)
    local c = o:GetClass()
    while c and c:IsValid() do
        local cname = c:GetFName():ToString()
        if stopAt and stopAt[cname] then break end
        c:ForEachProperty(function(p)
            cb(p:GetFName():ToString(), p:GetClass():GetFName():ToString(), cname, p)
        end)
        c = c:GetSuperStruct()
    end
end

local NUMERIC     = { FloatProperty = true, DoubleProperty = true, IntProperty = true, ByteProperty = true, Int64Property = true }
local STOP_ACTOR  = { Pawn = true, Character = true, Actor = true, Object = true }
local STOP_PS     = { PlayerState = true, Info = true, Actor = true, Object = true }
local STOP_WIDGET = { UserWidget = true, Widget = true, Visual = true, Object = true }

local TAG_CORE = cfg.NAME_TAG:gsub("^%s+", "")
local TAG_PATTERN = "%s*" .. TAG_CORE:gsub("%p", "%%%0")

local function stripTag(name)
    if not name then return nil end
    return (name:gsub(TAG_PATTERN, ""))
end
local function hasTag(name)
    return name ~= nil and name:find(TAG_CORE, 1, true) ~= nil
end

-- Ein Name ist nur gültig, wenn er druckbar und nicht leer ist
-- (schützt vor dem Datensalat-Bug aus v1)
local function plausibleName(n)
    if type(n) ~= "string" then return false end
    if #n == 0 or #n > 64 then return false end
    if n:find("[%z\1-\31]") then return false end
    if n:find("\239\191\189", 1, true) then return false end -- U+FFFD Ersatzzeichen
    return true
end

local function fmtNum(v)
    if v == nil then return "?" end
    if math.abs(v - math.floor(v + 0.5)) < 0.05 then return string.format("%d", math.floor(v + 0.5)) end
    return string.format("%.1f", v)
end

local function vec(v)
    if v == nil then return nil end
    local ok, r = pcall(function() return { X = v.X, Y = v.Y, Z = v.Z } end)
    if ok and type(r.X) == "number" then return r end
    return nil
end

local function dist(a, b)
    if not a or not b then return nil end
    local dx, dy, dz = a.X - b.X, a.Y - b.Y, a.Z - b.Z
    return math.sqrt(dx * dx + dy * dy + dz * dz) / cfg.UNITS_PER_METER
end

-- ------------------------------------------------------------
--  Spieler auslesen
-- ------------------------------------------------------------
local localPC, localPCAt = nil, -99999
local function getLocalPC()
    -- jede Sekunde neu suchen (Map-Wechsel: MenuPC -> PlayerControllerBP)
    if valid(localPC) and now - localPCAt < 1000 then return localPC end
    localPCAt = now
    localPC = nil
    local pcs = FindAllOf("PlayerController")
    if not pcs then return nil end
    for _, pc in ipairs(pcs) do
        if try("IsLocalController", function() return pc:IsLocalController() end) then
            localPC = pc; return pc
        end
    end
    return nil
end

local function getPlayerStates()
    local gs = FindFirstOf("GameStateBase")
    if not valid(gs) then return {} end
    local list = {}
    try("PlayerArray", function()
        gs.PlayerArray:ForEach(function(_, e)
            local ps = e:get()
            if valid(ps) then list[#list + 1] = ps end
        end)
    end)
    return list
end

-- WICHTIG: Property direkt lesen, NICHT GetPlayerName() aufrufen
-- (Rückgabe-Strings von Funktionen sind in UE4SS 3.0.1 kaputt)
local function psName(ps)
    local n = str(prop(ps, "PlayerNamePrivate"))
    if plausibleName(n) then return n end
    return nil
end

local function psPawn(ps)
    local p = prop(ps, "PawnPrivate")
    if valid(p) then return p end
    return nil
end

-- Pawn eines beliebigen Objekts (Pawn, Controller oder PlayerState)
local function toPawn(o)
    if not valid(o) then return nil end
    if classChainHas(o, "Pawn") then return o end
    if classChainHas(o, "Controller") then local p = prop(o, "Pawn"); if valid(p) then return p end end
    if classChainHas(o, "PlayerState") then return psPawn(o) end
    return nil
end

local function readHealth(pawn)
    if not valid(pawn) then return nil, false end
    local hp = prop(pawn, P_HEALTH)
    if type(hp) ~= "number" then
        -- Fallback: Config-Override
        if cfg.HEALTH_PROPERTY then hp = prop(pawn, cfg.HEALTH_PROPERTY) end
        if type(hp) ~= "number" then return nil, false end
    end
    local auth = try("HasAuthority", function() return pawn:HasAuthority() end)
    if auth then return hp, true end
    -- Client: "client health" ist evtl. die replizierte Variante
    local ch = prop(pawn, P_CLIENT_HEALTH)
    if type(ch) == "number" and ch > 0 then return ch, true end
    return hp, false
end

-- Client: eigene Leben aus der Lebensleiste des Spiel-HUDs lesen
-- (zeigt nur, was das Spiel ohnehin anzeigt)
local hudBarName = nil
local function hudBars(pc)
    local hud = pc and prop(pc, "HudGusRef") or nil
    if not valid(hud) then return {} end
    local bars = {}
    try("hudBars", function()
        forEachProp(hud, function(n, t)
            if t ~= "ObjectProperty" then return end
            local v = prop(hud, n)
            if valid(v) and classChainHas(v, "ProgressBar") then
                bars[#bars + 1] = { name = n, bar = v, percent = prop(v, "Percent") }
            end
        end, { UserWidget = true, Widget = true, Visual = true, Object = true })
    end)
    return bars
end

local function hudHealth(pc)
    local bars = hudBars(pc)
    if #bars == 0 then return nil end
    local pick = nil
    for _, b in ipairs(bars) do if b.name == hudBarName then pick = b end end
    if not pick then
        for _, b in ipairs(bars) do
            local l = b.name:lower()
            if l:find("health") or l:find("hp") or l:find("leben") then pick = b; break end
        end
        pick = pick or bars[1]
        hudBarName = pick.name
        log("HUD-Lebensleiste:", pick.name, "(von", #bars, "Leisten)")
    end
    if type(pick.percent) == "number" then return pick.percent * 100 end
    return nil
end

local function isDead(pawn, hp)
    if not valid(pawn) then return true end
    if prop(pawn, P_DEAD1) == true or prop(pawn, P_DEAD2) == true then return true end
    if hp and hp <= 0 then return true end
    return false
end

-- ------------------------------------------------------------
--  Spieler-Cache
-- ------------------------------------------------------------
local players = {}    -- key = PlayerState-Adresse
local localKey = nil
local onPlayerDied    -- forward
local onDeathCounter  -- forward

local function findPlayerByName(name)
    if not name then return nil end
    local clean = stripTag(name)
    for _, r in pairs(players) do if r.name == clean then return r end end
    return nil
end

local function findPlayerByPawn(pawn)
    if not valid(pawn) then return nil end
    local a = pawn:GetAddress()
    for _, r in pairs(players) do if r.pawnAddr == a then return r end end
    return nil
end

local tagTries, lastTagTry, tagKey = 0, -99999, nil

local function updatePlayers()
    local pc = getLocalPC()
    local localPS = pc and prop(pc, "PlayerState") or nil
    local localPSAddr = valid(localPS) and localPS:GetAddress() or nil

    local states = getPlayerStates()
    local seen = {}
    local tagged, named = 0, 0
    for _, ps in ipairs(states) do
        local key = ps:GetAddress()
        seen[key] = true
        local r = players[key]
        if not r then r = { alive = false, deathAt = -99999 }; players[key] = r end
        r.ps = ps
        local raw = psName(ps)
        r.raw = raw
        if raw then
            named = named + 1
            r.name = stripTag(raw)
            if hasTag(raw) then tagged = tagged + 1 end
        else
            r.name = r.name or "?"
        end
        r.isLocal = (key == localPSAddr)
        if r.isLocal then localKey = key end

        local pawn = psPawn(ps)
        r.pawn = pawn
        local hp, trusted = readHealth(pawn)
        if r.isLocal and hp and not trusted then
            local hh = hudHealth(pc)
            if hh then hp, trusted = hh, true end
        end
        r.hp, r.hpTrusted = hp, trusted
        local addr = pawn and pawn:GetAddress() or nil
        local pawnChanged = (addr ~= r.pawnAddr)
        local prevHp, prevMax = r.prevHp, r.maxSeen
        if pawnChanged then r.pawnAddr = addr; r.maxSeen = nil end
        if hp and (not r.maxSeen or hp > r.maxSeen) then r.maxSeen = hp end
        if pawn then
            local loc = vec(try("K2_GetActorLocation", function() return pawn:K2_GetActorLocation() end))
            if loc then r.loc = loc end
        end

        -- Nur echte Spielfiguren (mit Leben-Variable) zählen für Tod-Erkennung
        local hasHealth = hp ~= nil
        local nowAlive = hasHealth and not isDead(pawn, hp)
        if nowAlive then r.aliveLoc = r.loc end
        -- Tod nur zählen, wenn
        --  a) DIESELBE Figur von lebendig auf tot wechselt, oder
        --  b) die Figur verschwindet, nachdem sie Schaden hatte.
        -- Ein Figurenwechsel mit vollen Leben (Spawn, Lobby, Zuschauer-
        -- Kamera, Map-Wechsel) ist KEIN Tod.
        local died = false
        if r.alive and not nowAlive then
            if not pawnChanged then
                died = true
            elseif prevHp and prevMax and prevHp < prevMax then
                died = true
            end
        end
        r.prevHp = nowAlive and hp or nil

        -- "Last Hit By" laufend merken – beim Tod ist die Figur evtl. schon weg
        if pawnChanged then r.cachedLastHit, r.cachedLastHitName = nil, nil end
        if pawn then
            local lhb = prop(pawn, P_LAST_HIT)
            if valid(lhb) then r.cachedLastHit = lhb end
            local lhn = str(prop(pawn, P_LAST_HIT_NAME))
            if lhn and lhn ~= "" then r.cachedLastHitName = lhn end
        end

        -- Bananen in diesem Leben zählen (zwei Signale, das größere zählt):
        --  a) "Bannana Amount" sinkt   b) "Eating Bannana" geht an
        if pawnChanged then r.banAmt, r.eatingPrev = nil, nil end
        if pawn then
            local ban = prop(pawn, "Bannana Amount")
            if type(ban) == "number" then
                if r.banAmt and ban < r.banAmt then
                    r.banDec = (r.banDec or 0) + (r.banAmt - ban)
                    log("Banane (Amount", r.banAmt, "->", ban, ") von", r.name)
                end
                r.banAmt = ban
            end
            local eating = prop(pawn, "Eating Bannana") == true
            if eating and not r.eatingPrev then
                r.banEat = (r.banEat or 0) + 1
                log("Banane (Eating) von", r.name)
            end
            r.eatingPrev = eating
        end

        -- Kills/Deaths aus dem PlayerState (zählt der Server -> zuverlässig)
        local k1, k2 = prop(ps, "Kills"), prop(ps, "Player Kills")
        if type(k1) == "number" or type(k2) == "number" then
            local k = (type(k1) == "number" and k1 or 0) + (type(k2) == "number" and k2 or 0)
            if r.kills and k > r.kills then r.killsChangedAt = now end
            r.kills = k
        end
        local dc = prop(ps, "Deaths")
        if type(dc) == "number" then
            r.hasDeathCounter = true
            if r.deaths and dc > r.deaths and onDeathCounter then onDeathCounter(r, dc) end
            r.deaths = dc
        end

        if died then
            r.deathAt = now
            -- Infos sofort sichern, bevor der Pawn verschwindet
            local dl = pawn and vec(prop(pawn, P_DEATH_LOC)) or nil
            r.deathLoc = (dl and (dl.X ~= 0 or dl.Y ~= 0)) and dl or r.aliveLoc
            r.lastHitBy = pawn and prop(pawn, P_LAST_HIT) or nil
            r.lastHitByName = pawn and str(prop(pawn, P_LAST_HIT_NAME)) or nil
            if onPlayerDied then onPlayerDied(r) end
        end
        r.alive = nowAlive
    end
    for k in pairs(players) do if not seen[k] then players[k] = nil end end

    -- Handshake: eigenen Tag setzen – nur mit gültigem Namen, gedrosselt
    local me = localKey and players[localKey]
    -- neuer PlayerState (neue Lobby / Map) -> Versuche zurücksetzen
    if localKey ~= tagKey then tagKey = localKey; tagTries = 0; lastTagTry = -99999 end
    local tagWait = (tagTries < 5) and 5000 or 30000
    if cfg.REQUIRE_ALL_PLAYERS and pc and me and me.raw and not hasTag(me.raw)
        and lastTagTry + tagWait < now then
        lastTagTry = now; tagTries = tagTries + 1
        try("ServerChangeName", function() pc:ServerChangeName(me.raw .. cfg.NAME_TAG) end)
        log("Setze Namens-Tag:", me.raw .. cfg.NAME_TAG, "(Versuch " .. tagTries .. ")")
    end

    local total = #states
    if total == 0 then
        active = false; statusText = ""
    elseif not cfg.REQUIRE_ALL_PLAYERS then
        active = true; statusText = string.format(T.status_test, VERSION)
    elseif tagged == total then
        active = true; statusText = string.format(T.status_on, tagged, total)
    else
        active = false
        local missing = {}
        for _, r in pairs(players) do
            if not hasTag(r.raw) then missing[#missing + 1] = r.raw or "?" end
        end
        statusText = string.format(T.status_off, table.concat(missing, ", "))
    end
end

-- ------------------------------------------------------------
--  Overlay
-- ------------------------------------------------------------
local ui = nil
local uiCounter = 0
local feed = {}
local deathMsg = nil

local function setText(tb, s) try("SetText", function() tb:SetText(FText(s)) end) end
local function setVisible(w, on) try("SetVisibility", function() w:SetVisibility(on and 3 or 2) end) end
local function setColor(tb, c)
    try("SetColorAndOpacity", function() tb:SetColorAndOpacity({ SpecifiedColor = c, ColorUseRule = 0 }) end)
end

-- Positionierung: Anker bleiben (0,0) = oben links. Die Mod rechnet
-- die Position selbst aus der Bildschirmgröße aus (verschachtelte
-- Structs wie FAnchors kommen in UE4SS 3.0.1 nicht zuverlässig an).
local function place(slot, align, x, y)
    try("SetAutoSize", function() slot:SetAutoSize(true) end)
    try("SetAlignment", function() slot:SetAlignment({ X = align.X, Y = align.Y }) end)
    try("SetPosition", function() slot:SetPosition({ X = x, Y = y }) end)
end

local function viewportSize()
    local pc = getLocalPC()
    local wl = StaticFindObject("/Script/UMG.Default__WidgetLayoutLibrary")
    local w, h, sc = 1920, 1080, 1
    if valid(wl) and pc then
        local v = try("GetViewportSize", function() return wl:GetViewportSize(pc) end)
        if v and type(v.X) == "number" and v.X > 0 then w, h = v.X, v.Y end
        local s2 = try("GetViewportScale", function() return wl:GetViewportScale(pc) end)
        if type(s2) == "number" and s2 > 0 then sc = s2 end
    end
    return w / sc, h / sc, w, h, sc
end

-- ------------------------------------------------------------
--  Crosshair (gleiche Geometrie wie launcher/crosshair.py: rects())
-- ------------------------------------------------------------
local XH_DEFAULT = {
    COLOR = "FFFFFFFF",
    OUTLINE = true, OUTLINE_THICKNESS = 1, OUTLINE_OPACITY = 0.5,
    DOT = false, DOT_THICKNESS = 2, DOT_OPACITY = 1,
    INNER = { SHOW = true, LENGTH = 4, VLENGTH = 4, THICKNESS = 2, OFFSET = 2, OPACITY = 1 },
    OUTER = { SHOW = false, LENGTH = 2, VLENGTH = 2, THICKNESS = 2, OFFSET = 10, OPACITY = 0.35 },
    SCALE = 1,
}

local function xhConfig()
    local c = {}
    local src = cfg.CROSSHAIR or {}
    for k, v in pairs(XH_DEFAULT) do
        if type(v) == "table" then
            c[k] = {}
            for k2, v2 in pairs(v) do
                local s2 = src[k] and src[k][k2]
                if s2 == nil then c[k][k2] = v2 else c[k][k2] = s2 end
            end
        else
            if src[k] == nil then c[k] = v else c[k] = src[k] end
        end
    end
    return c
end

local function hexColor(h)
    h = tostring(h or "FFFFFFFF"):gsub("#", "")
    if #h == 6 then h = h .. "FF" end
    local function ch(i) return (tonumber(h:sub(i, i + 1), 16) or 255) / 255 end
    return ch(1), ch(3), ch(5), ch(7)
end

-- Liste von { left, top, w, h, r, g, b, a } relativ zur Bildschirmmitte.
-- Erst alle Outlines, dann die Füllungen.
local function crosshairRects(c)
    local r, g, b, a = hexColor(c.COLOR)
    local s = c.SCALE or 1
    local ot = c.OUTLINE and c.OUTLINE_THICKNESS or 0
    local outlines, fills = {}, {}
    local function add(cx, cy, w, h, alpha)
        if w <= 0 or h <= 0 or alpha <= 0 then return end
        fills[#fills + 1] = { (cx - w / 2) * s, (cy - h / 2) * s, w * s, h * s, r, g, b, alpha * a }
        if ot > 0 and c.OUTLINE_OPACITY > 0 then
            local ow, oh = w + 2 * ot, h + 2 * ot
            outlines[#outlines + 1] = { (cx - ow / 2) * s, (cy - oh / 2) * s, ow * s, oh * s, 0, 0, 0, c.OUTLINE_OPACITY }
        end
    end
    if c.DOT then add(0, 0, c.DOT_THICKNESS, c.DOT_THICKNESS, c.DOT_OPACITY) end
    for _, L in ipairs({ c.INNER, c.OUTER }) do
        if L.SHOW then
            local t, l, v, o, op = L.THICKNESS, L.LENGTH, L.VLENGTH, L.OFFSET, L.OPACITY
            add(o + l / 2, 0, l, t, op)
            add(-(o + l / 2), 0, l, t, op)
            add(0, o + v / 2, t, v, op)
            add(0, -(o + v / 2), t, v, op)
        end
    end
    local all = {}
    for _, q in ipairs(outlines) do all[#all + 1] = q end
    for _, q in ipairs(fills) do all[#all + 1] = q end
    return all
end

local function round(x) return math.floor(x + 0.5) end

local function placeRect(slot, x, y, w, h)
    try("XH.SetAutoSize", function() slot:SetAutoSize(false) end)
    try("XH.SetAlignment", function() slot:SetAlignment({ X = 0, Y = 0 }) end)
    try("XH.SetPosition", function() slot:SetPosition({ X = x, Y = y }) end)
    try("XH.SetSize", function() slot:SetSize({ X = w, Y = h }) end)
end

local function makeText(tree, canvas, name, size, align)
    uiCounter = uiCounter + 1
    local tb = StaticConstructObject(StaticFindObject("/Script/UMG.TextBlock"), tree, FName("PFSQoL_" .. name .. uiCounter))
    try("Font.Size", function() tb.Font.Size = size end)
    try("ShadowOffset", function() tb.ShadowOffset.X = 1.5; tb.ShadowOffset.Y = 1.5 end)
    try("ShadowColor", function()
        local c = tb.ShadowColorAndOpacity; c.R = 0; c.G = 0; c.B = 0; c.A = 0.85
    end)
    local slot = canvas:AddChildToCanvas(tb)
    try("SetAutoSize", function() slot:SetAutoSize(true) end)
    return tb, slot, align
end

local function buildUI()
    local gi = FindFirstOf("GameInstance")
    if not valid(gi) then return nil end
    uiCounter = uiCounter + 1
    local w = StaticConstructObject(StaticFindObject("/Script/UMG.UserWidget"), gi, FName("PFSQoL_Widget" .. uiCounter))
    w.WidgetTree = StaticConstructObject(StaticFindObject("/Script/UMG.WidgetTree"), w, FName("PFSQoL_Tree" .. uiCounter))
    local canvas = StaticConstructObject(StaticFindObject("/Script/UMG.CanvasPanel"), w.WidgetTree, FName("PFSQoL_Canvas" .. uiCounter))
    w.WidgetTree.RootWidget = canvas

    local u = { widget = w, feed = {}, slots = {} }
    local function add(key, size, align)
        local tb, slot = makeText(w.WidgetTree, canvas, key, size, align)
        u.slots[#u.slots + 1] = { key = key, slot = slot, align = align }
        return tb
    end
    -- Crosshair aus einfarbigen Image-Widgets (Outlines zuerst = darunter)
    u.xh = {}
    local imgClass = StaticFindObject("/Script/UMG.Image")
    for i, q in ipairs(crosshairRects(xhConfig())) do
        uiCounter = uiCounter + 1
        local img = StaticConstructObject(imgClass, w.WidgetTree, FName("PFSQoL_XH" .. i .. "_" .. uiCounter))
        local slot = canvas:AddChildToCanvas(img)
        try("XH.SetColor", function() img:SetColorAndOpacity({ R = q[5], G = q[6], B = q[7], A = q[8] }) end)
        u.xh[#u.xh + 1] = { img = img, slot = slot, rect = q }
    end
    u.hp = add("hp", cfg.HP_SIZE, { X = 0, Y = 1 })
    u.status = add("status", 13, { X = 0, Y = 0 })
    setColor(u.status, { R = 0.85, G = 0.85, B = 0.85, A = 0.75 })
    for i = 1, cfg.FEED_LINES do
        u.feed[i] = add("feed" .. i, cfg.FEED_SIZE, { X = 1, Y = 0 })
        setColor(u.feed[i], { R = 1, G = 0.92, B = 0.6, A = 1 })
    end
    u.death = add("death", 30, { X = 0.5, Y = 0.5 })
    setColor(u.death, { R = 1, G = 0.35, B = 0.3, A = 1 })
    try("Justification", function() u.death:SetJustification(1) end)

    try("RootVisibility", function() w:SetVisibility(3) end)
    w:AddToViewport(50)
    log("Overlay erstellt")
    return u
end

-- Zielposition (in Slate-Einheiten) für jedes Element
local function targetPos(key, W, H)
    if key == "cross" then return W / 2, H / 2 end
    if key == "hp" then return cfg.HP_POS.X, H + cfg.HP_POS.Y end
    if key == "status" then return 12, 8 end
    if key == "death" then return W / 2, H * 0.3 end
    local i = tonumber(key:match("^feed(%d+)$"))
    if i then return W + cfg.FEED_POS.X, cfg.FEED_POS.Y + (i - 1) * (cfg.FEED_SIZE + 8) end
    return 0, 0
end

local lastLayoutKey, layoutLogged = nil, false
local function relayout(u, force)
    local W, H, pw, ph, sc = viewportSize()
    local k = string.format("%d:%d", math.floor(W), math.floor(H))
    if not force and k == lastLayoutKey then return end
    lastLayoutKey = k
    for _, e in ipairs(u.slots) do
        local x, y = targetPos(e.key, W, H)
        place(e.slot, e.align, x, y)
    end
    -- Crosshair: gleiche Rundung wie die Launcher-Vorschau
    local cx, cy = math.floor(W / 2), math.floor(H / 2)
    for _, e in ipairs(u.xh or {}) do
        local q = e.rect
        placeRect(e.slot, math.floor(cx + q[1]), math.floor(cy + q[2]), math.max(1, round(q[3])), math.max(1, round(q[4])))
    end
    -- Diagnose: wo ist das erste Crosshair-Rechteck gelandet?
    local first = u.xh and u.xh[1]
    local p = first and try("GetPosition", function() return first.slot:GetPosition() end)
    local sz = first and try("GetSize", function() return first.slot:GetSize() end)
    log(string.format("Layout: Viewport %dx%d px, Scale %.2f -> %dx%d Einheiten",
        math.floor(pw), math.floor(ph), sc, math.floor(W), math.floor(H)),
        "| Crosshair-Teile:", #(u.xh or {}),
        "| erstes Pos:", p and (tostring(p.X) .. "," .. tostring(p.Y)) or "?",
        "Groesse:", sz and (tostring(sz.X) .. "x" .. tostring(sz.Y)) or "?")
end

local function ensureUI()
    if ui and valid(ui.widget) then
        local inVp = try("IsInViewport", function() return ui.widget:IsInViewport() end)
        if inVp then relayout(ui, false); return ui end
        if inVp == false then try("AddToViewport", function() ui.widget:AddToViewport(50) end); return ui end
    end
    local ok, u = pcall(buildUI)
    if ok then ui = u else log("Overlay-Fehler:", u); ui = nil end
    if ui then lastLayoutKey = nil; relayout(ui, true) end
    return ui
end

local function renderUI()
    local u = ensureUI()
    if not u then return end
    local show = enabledByUser and active

    setText(u.status, statusText)
    setVisible(u.status, enabledByUser and statusText ~= "")

    local me = localKey and players[localKey]
    -- Crosshair nur, wenn die eigene Spielfigur lebt (nicht im Menü / Spawn-Bildschirm)
    local xhOn = show and cfg.SHOW_CROSSHAIR and me ~= nil and me.alive
    if xhOn ~= u.xhVisible then
        u.xhVisible = xhOn
        for _, e in ipairs(u.xh) do setVisible(e.img, xhOn) end
    end

    if show and cfg.SHOW_HP and me and me.hp and me.alive then
        local mx = me.maxSeen
        local s = "HP " .. fmtNum(math.max(me.hp, 0))
        if mx and mx > 0 then s = s .. " / " .. fmtNum(mx) end
        if not me.hpTrusted then s = s .. " ~" end
        setText(u.hp, s)
        local frac = (mx and mx > 0) and (me.hp / mx) or 1
        setColor(u.hp, frac > 0.5 and { R = 1, G = 1, B = 1, A = 1 }
            or frac > 0.25 and { R = 1, G = 0.8, B = 0.2, A = 1 } or { R = 1, G = 0.3, B = 0.25, A = 1 })
        setVisible(u.hp, true)
    else
        setVisible(u.hp, false)
    end

    local i = 1
    for k = #feed, 1, -1 do
        local e = feed[k]
        if e["until"] > now and i <= cfg.FEED_LINES then
            setText(u.feed[i], e.text); setVisible(u.feed[i], show and cfg.SHOW_KILL_INFO); i = i + 1
        end
    end
    for j = i, cfg.FEED_LINES do setVisible(u.feed[j], false) end
    while #feed > 20 do table.remove(feed, 1) end

    if show and cfg.SHOW_DEATH_INFO and deathMsg and deathMsg["until"] > now then
        setText(u.death, deathMsg.text); setVisible(u.death, true)
    else
        setVisible(u.death, false)
    end
end

-- ------------------------------------------------------------
--  Kill-Erkennung
-- ------------------------------------------------------------
local recentKills = {}

local function plural(n, one, many) return n == 1 and one or many end

local function reportKill(killer, victim, source, khpOverride, bananas)
    if not victim then return end
    local vkey = victim.name or "?"
    if recentKills[vkey] and recentKills[vkey] + 2000 > now then return end
    recentKills[vkey] = now

    -- Killstreak: Kills seit dem letzten Tod (aus unseren eigenen Kill-Events)
    local streak = victim.streak or 0
    victim.streak = 0
    if killer and killer ~= victim then killer.streak = (killer.streak or 0) + 1 end

    local extras = {}
    if cfg.SHOW_STREAK ~= false and streak >= 1 then
        extras[#extras + 1] = string.format(T.streak, streak)
    end
    if cfg.SHOW_BANANAS ~= false and bananas then
        extras[#extras + 1] = string.format("%d %s", bananas, plural(bananas, T.banana_one, T.banana_many))
    end
    local extraTxt = (#extras > 0) and ("  ·  " .. table.concat(extras, "  ·  ")) or ""

    local d = killer and dist(killer.loc, victim.deathLoc or victim.aliveLoc or victim.loc) or nil
    local khp = khpOverride
    if khp == nil and killer and killer.hpTrusted and killer.alive then khp = killer.hp end
    local dTxt = d and string.format("%.0f", d) or "?"

    local line
    if killer and killer ~= victim then
        line = string.format(T.feed_kill, killer.name, victim.name, dTxt, fmtNum(khp)) .. extraTxt
    else
        line = string.format(T.feed_died, victim.name) .. extraTxt
    end
    feed[#feed + 1] = { text = line, ["until"] = now + cfg.FEED_SECONDS * 1000 }
    log("Kill [" .. source .. "]:", line)

    if victim.isLocal then
        local t
        if killer and killer ~= victim then
            t = string.format(T.death_by, killer.name, killer.name, fmtNum(khp), dTxt)
        else
            t = T.death_self
        end
        if #extras > 0 then t = t .. "\n" .. T.your_life .. table.concat(extras, "  ·  ") end
        deathMsg = { text = t, ["until"] = now + 6000 }
    end
end

-- Haupt-Quelle: Deaths-Zähler im PlayerState ist gestiegen
local function resolveKiller(r, snap)
    local killer, via = nil, nil
    local kobj = prop(r.ps, "Killer")
    if valid(kobj) then
        if classChainHas(kobj, "PlayerState") then killer = players[kobj:GetAddress()] end
        killer = killer or findPlayerByPawn(toPawn(kobj))
        if killer then via = "PS.Killer(" .. className(kobj) .. ")" end
    end
    if not killer and valid(snap.lastHit) then
        if classChainHas(snap.lastHit, "PlayerState") then killer = players[snap.lastHit:GetAddress()] end
        killer = killer or findPlayerByPawn(toPawn(snap.lastHit))
        if killer then via = "LastHitBy(" .. className(snap.lastHit) .. ")" end
    end
    if not killer and snap.lastHitName then
        killer = findPlayerByName(snap.lastHitName)
        if killer then via = "LastHitByName" end
    end
    if not killer then
        for _, o in pairs(players) do
            if o ~= r and o.killsChangedAt and math.abs(o.killsChangedAt - snap.at) <= 1500 then
                killer = o; via = "Kills-Zaehler"
            end
        end
    end
    log("Tod von", r.name, "| Killer:", killer and killer.name or "-", "via", via or "-",
        "| PS.Killer:", valid(kobj) and className(kobj) or "-",
        "| LastHit:", valid(snap.lastHit) and className(snap.lastHit) or "-", "| LastHitName:", tostring(snap.lastHitName))
    return killer
end

-- Der Host kennt die echten Leben aller Spieler, Clients nicht.
-- Deshalb schreibt der Host beim Kill Killer + Rest-HP in das (vom Spiel
-- ungenutzte, replizierte) Feld "Score" im PlayerState des Opfers:
--   Score = 1.000.000 + Seq * 1.000.000 + KillerId * 1000 + HP
--   Seq      = Tode des Opfers mod 10  (gehört zu genau diesem Tod)
--   KillerId = PlayerId des Killers mod 1000 (999 = kein Killer)
--   HP       = 0..998 (999 = unbekannt)
-- Maximal ~11 Mio. -> passt exakt in eine float-Zahl.
local SCORE_BASE = 1000000
local NO_KILLER, NO_HP = 999, 999

local function playerKey(r)
    local id = prop(r.ps, "PlayerId")
    if type(id) == "number" then return math.floor(id) % 1000 end
    return nil
end

local function encodeKill(victim, deaths, killer, hp)
    if cfg.SHARE_KILL_HP == false then return end
    local kid = (killer and killer ~= victim) and playerKey(killer) or nil
    if kid == nil or kid == NO_KILLER then kid = NO_KILLER end
    local h = hp and math.max(0, math.min(998, math.floor(hp + 0.5))) or NO_HP
    local v = SCORE_BASE + (deaths % 10) * 1000000 + kid * 1000 + h
    try("writeScore", function() victim.ps.Score = v end)
    try("ForceNetUpdate", function() victim.ps:ForceNetUpdate() end)
end

local function decodeKill(victim, deaths)
    local sc = prop(victim.ps, "Score")
    if type(sc) ~= "number" or sc < SCORE_BASE then return nil end
    local rest = math.floor(sc - SCORE_BASE + 0.5)
    if math.floor(rest / 1000000) ~= deaths % 10 then return nil end
    local kid = math.floor((rest % 1000000) / 1000)
    local hp = rest % 1000
    local killer = nil
    if kid ~= NO_KILLER then
        for _, o in pairs(players) do if o ~= victim and playerKey(o) == kid then killer = o end end
    end
    return { killer = killer, hasKiller = kid ~= NO_KILLER, hp = (hp ~= NO_HP) and hp or nil }
end

-- Zweites Feld "StartTime" (int32, repliziert):
--   StartTime = 1.000.000.000 + Seq * 100.000.000 + Bananen
local START_BASE = 1000000000

local function encodeBananas(victim, deaths, bananas)
    if cfg.SHARE_KILL_HP == false or bananas == nil then return end
    local v = START_BASE + (deaths % 10) * 100000000 + math.max(0, math.min(999, bananas))
    try("writeStartTime", function() victim.ps.StartTime = v end)
end

local function decodeBananas(victim, deaths)
    local st = prop(victim.ps, "StartTime")
    if type(st) ~= "number" or st < START_BASE then return nil end
    local rest = math.floor(st - START_BASE)
    if math.floor(rest / 100000000) ~= deaths % 10 then return nil end
    return rest % 1000
end

local function waitForHost(r, localKiller, deaths, tries)
    local d = decodeKill(r, deaths)
    if d then
        -- Bananen kommen im selben Update; kurz nachschauen
        reportKill(d.killer or localKiller, r, "Host", d.hp, decodeBananas(r, deaths))
        return
    end
    if tries >= 30 then reportKill(localKiller, r, "Deaths(ohne Host-Daten)", nil, nil); return end
    ExecuteWithDelay(100, function()
        ExecuteInGameThread(function()
            local ok, err = pcall(waitForHost, r, localKiller, deaths, tries + 1)
            if not ok then log("Fehler waitForHost:", err) end
        end)
    end)
end

onDeathCounter = function(r, deaths)
    local snap = { lastHit = r.cachedLastHit, lastHitName = r.cachedLastHitName,
                   loc = r.aliveLoc or r.loc, at = now,
                   bananas = math.max(r.banDec or 0, r.banEat or 0) }
    r.banDec, r.banEat = 0, 0   -- neues Leben beginnt
    r.deathAt = now
    r.deathLoc = snap.loc
    -- kurz warten, bis der Server Killer/Kills aktualisiert hat
    ExecuteWithDelay(300, function()
        ExecuteInGameThread(function()
            local ok, err = pcall(function()
                r.deathLoc = snap.loc
                local killer = resolveKiller(r, snap)
                local isHost = try("psAuthority", function() return r.ps:HasAuthority() end)
                if isHost then
                    local khp = (killer and killer ~= r and killer.hpTrusted and killer.alive) and killer.hp or nil
                    encodeBananas(r, deaths, snap.bananas)   -- vor encodeKill (ForceNetUpdate)
                    encodeKill(r, deaths, killer, khp)
                    reportKill(killer, r, "Deaths", khp, snap.bananas)
                else
                    -- Client: auf Killer + HP vom Host warten (max. 3 s)
                    waitForHost(r, killer, deaths, 0)
                end
            end)
            if not ok then log("Fehler bei Tod-Auswertung:", err) end
        end)
    end)
end

-- Ersatz-Quelle (nur falls es keinen Deaths-Zähler gibt): Leben auf 0
onPlayerDied = function(r)
    if r.hasDeathCounter then return end
    local killer = nil
    local lhb = r.lastHitBy
    if valid(lhb) then
        log("Last Hit By =", className(lhb))
        killer = findPlayerByPawn(toPawn(lhb))
        if not killer and classChainHas(lhb, "PlayerState") then killer = players[lhb:GetAddress()] end
    end
    if not killer and r.lastHitByName and r.lastHitByName ~= "" then
        killer = findPlayerByName(r.lastHitByName)
    end
    if killer then
        reportKill(killer, r, "LastHitBy")
    else
        -- kurz auf Killfeed/Hook warten, sonst neutraler Eintrag
        ExecuteWithDelay(1200, function()
            ExecuteInGameThread(function() reportKill(nil, r, "Fallback") end)
        end)
    end
end

-- Neben-Quelle: Strings aus Killfeed / Hook mit Spielernamen abgleichen
local function matchNames(strings)
    local order, found = {}, {}
    local list = {}
    for _, r in pairs(players) do if r.name and r.name ~= "?" then list[#list + 1] = r end end
    table.sort(list, function(a, b) return #a.name > #b.name end)
    for _, s in ipairs(strings) do
        local clean = stripTag(s)
        local hits, used = {}, {}
        for _, r in ipairs(list) do
            if not found[r] then
                local a, b = clean:find(r.name, 1, true)
                if a then
                    local overlap = false
                    for _, u in ipairs(used) do if a <= u[2] and b >= u[1] then overlap = true end end
                    if not overlap then used[#used + 1] = { a, b }; hits[#hits + 1] = { pos = a, r = r } end
                end
            end
        end
        table.sort(hits, function(x, y) return x.pos < y.pos end)
        for _, h in ipairs(hits) do found[h.r] = true; order[#order + 1] = h.r end
    end
    return order
end

local function handleNames(strings, source)
    local rs = matchNames(strings)
    log(source .. ":", table.concat(strings, " | "))
    if #rs < 2 then return end
    local a, b = rs[1], rs[2]
    local victim, killer
    if a.deathAt > b.deathAt then victim, killer = a, b
    elseif b.deathAt > a.deathAt then victim, killer = b, a
    else victim, killer = b, a end
    if victim.deathAt + 3000 > now then reportKill(killer, victim, source) end
end

local function collectWidgetStrings(widget)
    local out = {}
    try("collectWidgetStrings", function()
        forEachProp(widget, function(n, t)
            local v = prop(widget, n)
            if v == nil then return end
            if t == "StrProperty" or t == "TextProperty" or t == "NameProperty" then
                local s = str(v); if s and s ~= "" then out[#out + 1] = s end
            elseif t == "ObjectProperty" and valid(v) then
                if classChainHas(v, "TextBlock") then
                    -- Text als Property lesen (Funktions-Rückgaben sind unzuverlässig)
                    local s = str(prop(v, "Text")); if s and s ~= "" then out[#out + 1] = s end
                elseif classChainHas(v, "PlayerState") then
                    local s = psName(v); if s then out[#out + 1] = s end
                end
            end
        end, STOP_WIDGET)
    end)
    return out
end

-- ------------------------------------------------------------
--  Hooks
-- ------------------------------------------------------------
local lastFeedEl, lastKilledBy = nil, nil

NotifyOnNewObject(PATH_KILLFEED_ELEMENT, function(el)
    lastFeedEl = el
    ExecuteWithDelay(150, function()
        ExecuteInGameThread(function()
            if valid(el) then handleNames(collectWidgetStrings(el), "Killfeed") end
        end)
    end)
end)

NotifyOnNewObject(PATH_KILLED_BY, function(w)
    lastKilledBy = w
    ExecuteWithDelay(150, function()
        ExecuteInGameThread(function()
            if valid(w) then log("KilledBy:", table.concat(collectWidgetStrings(w), " | ")) end
        end)
    end)
end)

-- Hook auf die Killfeed-Funktion des PlayerControllers.
-- Die Klasse ist erst geladen, wenn man in einer Map ist -> später registrieren.
local hooksDone = false
local function paramToString(p)
    local v = try("hookParam", function() return p:get() end)
    if v == nil then return nil end
    local s = str(v)
    if s then return s end
    if valid(v) then
        if classChainHas(v, "PlayerState") then return psName(v) end
        local mn = str(prop(v, P_MY_NAME)); if mn then return mn end
        return className(v)
    end
    return nil
end

local PATH_PC = nil
local function pcClassPath()
    if PATH_PC then return PATH_PC end
    local pc = getLocalPC()
    if not pc then return nil end
    local full = try("pcClass", function() return pc:GetClass():GetFullName() end)
    -- "BlueprintGeneratedClass /Game/Blueprints/PlayerControllerBP.PlayerControllerBP_C"
    local path = full and full:match("%s(/Game/%S+)$")
    -- Im Hauptmenü gibt es nur MenuPC -> warten, bis wir in einer Map sind
    if path and path:find("PlayerControllerBP", 1, true) then
        PATH_PC = path; log("PlayerController-Klasse:", path)
    end
    return PATH_PC
end

local function tryRegisterHooks()
    if hooksDone then return end
    if not pcClassPath() then return end
    hooksDone = true
    for _, fn in ipairs({ "Add Kill To Box Client", "Kill Confirm Widget" }) do
        local ok, err = pcall(function()
            RegisterHook(PATH_PC .. ":" .. fn, function(self, ...)
                local strings = {}
                for i = 1, select("#", ...) do
                    local s = paramToString(select(i, ...))
                    if s then strings[#strings + 1] = s end
                end
                handleNames(strings, "Hook " .. fn)
            end)
        end)
        log("Hook", fn, ok and "OK" or ("FEHLER: " .. tostring(err)))
    end
end

-- ------------------------------------------------------------
--  Debug-Dump (F7)
-- ------------------------------------------------------------
local function dumpObj(title, o, stop)
    if not valid(o) then log("--", title, ": (nicht vorhanden)"); return end
    log("======", title, o:GetFullName())
    forEachProp(o, function(n, t, owner)
        local v = prop(o, n)
        local val = ""
        if NUMERIC[t] or t == "BoolProperty" then val = tostring(v)
        elseif t == "StrProperty" or t == "TextProperty" or t == "NameProperty" then val = '"' .. (str(v) or "") .. '"'
        elseif t == "ObjectProperty" and valid(v) then val = className(v) end
        log(string.format("   [%s] %s : %s = %s", owner, n, t, val))
    end, stop)
end

local function dumpFunctionParams(clsPath, needles)
    local cls = StaticFindObject(clsPath)
    if not valid(cls) then log("--", clsPath, "nicht geladen"); return end
    log("====== Funktions-Parameter", clsPath)
    try("ForEachFunction", function()
        cls:ForEachFunction(function(f)
            local fname = f:GetFName():ToString()
            local match = false
            for _, n in ipairs(needles) do if fname:lower():find(n, 1, true) then match = true end end
            if not match then return end
            local params = {}
            f:ForEachProperty(function(p)
                params[#params + 1] = p:GetFName():ToString() .. ":" .. p:GetClass():GetFName():ToString()
            end)
            log("   fn", fname, "(" .. table.concat(params, ", ") .. ")")
        end)
    end)
end

local function doDump()
    log("############ DUMP v" .. VERSION .. " ############")
    local pc = getLocalPC()
    local pawn = pc and prop(pc, "Pawn") or nil
    if valid(pawn) then
        log("Pawn:", className(pawn), "Health:", tostring(prop(pawn, P_HEALTH)), "client:", tostring(prop(pawn, P_CLIENT_HEALTH)),
            "IsDead?:", tostring(prop(pawn, P_DEAD1)), "Dead?:", tostring(prop(pawn, P_DEAD2)),
            "LastHitBy:", valid(prop(pawn, P_LAST_HIT)) and className(prop(pawn, P_LAST_HIT)) or "-",
            "LastHitByName:", tostring(str(prop(pawn, P_LAST_HIT_NAME))), "MyName:", tostring(str(prop(pawn, P_MY_NAME))),
            "Authority:", tostring(try("HasAuthority", function() return pawn:HasAuthority() end)))
    end
    for _, b in ipairs(hudBars(pc)) do log("HUD-Leiste:", b.name, "Percent =", tostring(b.percent)) end
    for _, r in pairs(players) do
        log("Score von", r.name, "=", tostring(prop(r.ps, "Score")), "| PlayerId =", tostring(prop(r.ps, "PlayerId")),
            "| StartTime =", tostring(prop(r.ps, "StartTime")), "| Streak =", tostring(r.streak),
            "| Bananen-Leben =", tostring(math.max(r.banDec or 0, r.banEat or 0)), "| Amount =", tostring(r.banAmt))
    end
    dumpObj("Letztes Killfeed-Element", lastFeedEl, STOP_WIDGET)
    dumpObj("Letztes KilledBy-Widget", lastKilledBy, STOP_WIDGET)
    log("Spieler-Cache:")
    for _, r in pairs(players) do
        log(string.format("   name=%s raw=%s hp=%s max=%s trusted=%s alive=%s local=%s",
            tostring(r.name), tostring(r.raw), tostring(r.hp), tostring(r.maxSeen), tostring(r.hpTrusted),
            tostring(r.alive), tostring(r.isLocal)))
    end
    log("Status:", statusText, "| Overlay:", ui and "ja" or "nein")
end

-- ------------------------------------------------------------
--  Tasten & Hauptschleife
-- ------------------------------------------------------------
RegisterKeyBind(cfg.KEY_TOGGLE, function()
    enabledByUser = not enabledByUser
    log("Overlay", enabledByUser and "an" or "aus")
end)

RegisterKeyBind(cfg.KEY_DUMP, function()
    ExecuteInGameThread(function()
        local ok, err = pcall(doDump)
        if not ok then log("Dump-Fehler:", err) end
    end)
end)

local lastErr = -99999
LoopAsync(TICK_MS, function()
    ExecuteInGameThread(function()
        now = now + TICK_MS
        local ok, err = pcall(function()
            tryRegisterHooks()
            updatePlayers()
            renderUI()
        end)
        if not ok and lastErr + 5000 < now then lastErr = now; log("Fehler:", err) end
    end)
    return false
end)

log("v" .. VERSION .. " geladen – F6: Overlay an/aus, F7: Debug-Dump")
