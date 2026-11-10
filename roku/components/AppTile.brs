sub init()
    m.outline = m.top.findNode("outline")
    m.surface = m.top.findNode("surface")
    m.band = m.top.findNode("nameBand")
    m.initial = m.top.findNode("initial")
    m.icon = m.top.findNode("icon")
    m.name = m.top.findNode("name")
    m.icon.observeField("loadStatus", "artChanged")
end sub

sub contentChanged()
    content = m.top.itemContent
    if content = invalid then return
    m.name.text = content.title
    m.initial.text = content.description
    m.initial.visible = true
    m.icon.visible = false
    if m.icon.uri <> content.HDPosterUrl then m.icon.uri = content.HDPosterUrl
    artChanged()
end sub

sub artChanged()
    ready = m.icon.uri <> "" and m.icon.loadStatus = "ready"
    m.icon.visible = ready
    m.initial.visible = not ready
end sub

sub focusChanged()
    focused = m.top.itemHasFocus
    m.outline.visible = focused
    m.surface.color = "#38254F"
    m.band.color = "#231833"
    if focused
        m.surface.color = "#563880"
        m.band.color = "#4B2D71"
    end if
end sub
