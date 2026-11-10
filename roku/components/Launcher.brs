sub init()
    m.home = m.top.findNode("home")
    m.host = m.top.findNode("moduleHost")
    m.menu = m.top.findNode("menu")
    m.status = m.top.findNode("status")
    m.server = m.top.findNode("server")
    m.timer = m.top.findNode("libraryTimer")
    m.timer.observeField("fire", "libraryTimedOut")
    m.menu.observeField("itemSelected", "selected")
    m.registry = CreateObject("roRegistrySection", "RokuAppLauncher")
    m.noirRegistry = CreateObject("roRegistrySection", "NoirSyncplay")
    m.noirLibrary = ReadAsciiFile("pkg:/noir-library.txt")
    m.base = m.registry.Read("server")
    if m.base = "" then m.base = normalizeAddress(ReadAsciiFile("pkg:/server.txt"))
    m.task = invalid
    m.pending = invalid
    m.active = invalid
    m.libraries = {}
    refresh()
end sub

function normalizeAddress(raw as String) as String
    url = raw.Trim()
    if url = "" then return ""
    if Instr(1, url, "://") = 0 then url = "http://" + url
    if Right(url, 1) = "/" then url = Left(url, Len(url) - 1)
    pattern = CreateObject("roRegex", "^https?://[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]{1,5})?$", "")
    if not pattern.IsMatch(url) then return ""
    return url
end function

sub refresh()
    if m.task <> invalid
        m.task.unobserveField("result")
        m.task.control = "stop"
        m.task = invalid
    end if
    showRows([])
    m.server.text = m.base
    if m.base = ""
        m.status.text = "Set up the server to see your apps."
        return
    end if
    m.status.text = "Looking for apps…"
    m.task = CreateObject("roSGNode", "FetchCatalog")
    m.task.url = m.base + "/catalog.json"
    m.task.observeField("result", "catalogReady")
    m.task.control = "run"
end sub

sub catalogReady(event as Object)
    result = event.GetData()
    if result.error <> invalid
        m.status.text = result.error
        return
    end if
    catalog = result.catalog
    if type(catalog) <> "roAssociativeArray"
        m.status.text = "The catalog is not a valid JSON object."
        return
    end if
    if catalog.version <> 1 or type(catalog.apps) <> "roArray"
        m.status.text = "Unsupported catalog format."
        return
    end if
    entries = []
    seen = {}
    identifier = CreateObject("roRegex", "^[A-Za-z][A-Za-z0-9_]{0,79}$", "")
    path = CreateObject("roRegex", "^/apps/[A-Za-z0-9_-]+\.zip$", "")
    for each app in catalog.apps
        if type(app) = "roAssociativeArray"
            if isText(app.title) and isText(app.id) and isText(app.component) and isText(app.path)
                if app.title.Trim() <> "" and identifier.IsMatch(app.id) and identifier.IsMatch(app.component) and path.IsMatch(app.path)
                    if not seen.DoesExist(app.id)
                        seen[app.id] = true
                        entries.Push(app)
                    end if
                end if
            end if
        end if
        if entries.Count() >= 100 then exit for
    end for
    showRows(entries)
    m.status.text = "Choose an app"
    if entries.IsEmpty() then m.status.text = "The server has no compatible apps."
end sub

function isText(value as Dynamic) as Boolean
    return type(value) = "String" or type(value) = "roString"
end function

sub showRows(entries as Object)
    m.entries = entries
    root = CreateObject("roSGNode", "ContentNode")
    for each app in entries
        row = root.CreateChild("ContentNode")
        row.title = app.title
    end for
    row = root.CreateChild("ContentNode")
    row.title = "Refresh Catalog"
    row = root.CreateChild("ContentNode")
    row.title = "Configure Server"
    m.menu.content = root
    m.menu.jumpToItem = 0
    m.menu.SetFocus(true)
end sub

sub selected(event as Object)
    if m.pending <> invalid then return
    index = event.GetData()
    if index < 0 then return
    if index < m.entries.Count()
        loadModule(m.entries[index])
    else if index = m.entries.Count()
        refresh()
    else
        editServer()
    end if
end sub

sub editServer()
    dialog = CreateObject("roSGNode", "KeyboardDialog")
    dialog.title = "Server (for example: 192.168.1.10:8765)"
    dialog.text = m.base
    dialog.buttons = ["Save", "Cancel"]
    dialog.observeField("buttonSelected", "serverSelected")
    m.top.dialog = dialog
end sub

sub serverSelected(event as Object)
    dialog = m.top.dialog
    if event.GetData() = 0
        address = normalizeAddress(dialog.text)
        if address = ""
            dialog.title = "Enter a valid server address or hostname"
            return
        end if
        m.registry.Write("server", address)
        if not m.registry.Flush()
            dialog.title = "Could not save the server"
            return
        end if
        m.base = address
        refresh()
    end if
    dialog.close = true
end sub

sub loadModule(app as Object)
    uri = m.base + app.path
    if m.libraries.DoesExist(app.id)
        cached = m.libraries[app.id]
        if cached.uri <> uri
            m.status.text = "Reopen the launcher to use a different server for this app."
        else
            openModule(app)
        end if
        return
    end if
    library = CreateObject("roSGNode", "ComponentLibrary")
    library.id = app.id
    m.top.AppendChild(library)
    m.pending = {app: app, node: library}
    library.observeField("loadStatus", "libraryStatus")
    m.status.text = "Loading " + app.title + "…"
    m.timer.control = "start"
    library.uri = uri
end sub

sub libraryStatus(event as Object)
    if m.pending = invalid then return
    status = event.GetData()
    if status = "ready"
        pending = m.pending
        m.pending = invalid
        m.timer.control = "stop"
        pending.node.unobserveField("loadStatus")
        m.libraries[pending.app.id] = pending.node
        openModule(pending.app)
    else if status = "failed"
        cancelLoad("Could not load the app.")
    end if
end sub

sub libraryTimedOut()
    cancelLoad("The download timed out.")
end sub

sub cancelLoad(message as String)
    if m.pending = invalid then return
    m.timer.control = "stop"
    node = m.pending.node
    m.pending = invalid
    node.unobserveField("loadStatus")
    m.top.RemoveChild(node)
    m.status.text = message
end sub

sub openModule(app as Object)
    module = CreateObject("roSGNode", app.id + ":" + app.component)
    if module = invalid
        m.status.text = "The library does not contain the requested component."
        return
    end if
    m.status.text = "Choose an app"
    m.active = module
    if module.HasField("dialog") then module.observeField("dialog", "moduleDialog")
    if app.id = m.noirLibrary and app.component = "NoirModule" and module.HasField("noirSettings")
        module.noirSettings = loadNoirSettings()
        module.observeField("settingsChanged", "saveNoirSettings")
        module.observeField("fontRequested", "setCaptionFont")
    end if
    if module.HasField("transportResponse") then module.observeField("transportResponse", "moduleTransportResponse")
    m.host.AppendChild(module)
    m.home.visible = false
    if module.HasField("running") then module.running = true
    if app.id = m.noirLibrary and module.HasField("captionFont")
        module.captionFont = makeNoirFont({size: 42, bold: false})
    end if
    if module.HasField("focusRequested")
        module.focusRequested = true
    else
        module.SetFocus(true)
    end if
end sub

function loadNoirSettings() as Object
    settings = ParseJson(ReadAsciiFile("pkg:/noir-defaults.json"))
    if settings = invalid then settings = {}
    if m.noirRegistry.Exists("url")
        previous = m.noirRegistry.Read("url")
        if settings.migrateFrom = invalid or previous <> settings.migrateFrom then settings.url = previous
    end if
    if m.noirRegistry.Exists("token") then settings.token = m.noirRegistry.Read("token")
    return settings
end function

function makeNoirFont(style as Object) as Object
    font = CreateObject("roSGNode", "Font")
    font.uri = "pkg:/fonts/NotoSansCJKsc-Regular.otf"
    if style.bold then font.uri = "pkg:/fonts/NotoSansCJKsc-Bold.otf"
    font.size = style.size
    return font
end function

sub setCaptionFont(event as Object)
    if m.active <> invalid then m.active.captionFont = makeNoirFont(event.GetData())
end sub

sub saveNoirSettings(event as Object)
    settings = event.GetData()
    m.noirRegistry.Write("url", settings.url)
    m.noirRegistry.Write("token", settings.token)
    m.noirRegistry.Flush()
end sub

sub moduleDialog(event as Object)
    m.top.dialog = event.GetData()
end sub

sub forwardTransport()
    if m.active <> invalid
        if m.active.HasField("transportCommand") then m.active.transportCommand = m.top.transportCommand
    end if
end sub

sub moduleTransportResponse(event as Object)
    m.top.transportResponse = event.GetData()
end sub

sub closeModule()
    if m.active.HasField("running") then m.active.running = false
    if m.active.HasField("dialog") then m.active.unobserveField("dialog")
    if m.active.HasField("transportResponse") then m.active.unobserveField("transportResponse")
    if m.active.HasField("settingsChanged") then m.active.unobserveField("settingsChanged")
    if m.active.HasField("fontRequested") then m.active.unobserveField("fontRequested")
    m.host.RemoveChild(m.active)
    m.active = invalid
    m.home.visible = true
    m.menu.SetFocus(true)
end sub

function onKeyEvent(key as String, press as Boolean) as Boolean
    if not press then return false
    if m.active <> invalid
        if key = "back"
            closeModule()
            return true
        end if
    else if m.pending <> invalid
        if key = "back" then cancelLoad("Download canceled.")
        return true
    else if key = "options" or key = "info"
        editServer()
        return true
    end if
    return false
end function
