sub init()
    m.top.functionName = "fetch"
end sub

sub fetch()
    port = CreateObject("roMessagePort")
    transfer = CreateObject("roUrlTransfer")
    transfer.SetMessagePort(port)
    transfer.SetCertificatesFile("common:/certs/ca-bundle.crt")
    transfer.SetUrl(m.top.url)
    if not transfer.AsyncGetToString()
        m.top.result = {error: "Could not start the connection."}
        return
    end if
    event = wait(8000, port)
    if event = invalid
        transfer.AsyncCancel()
        m.top.result = {error: "The server did not respond."}
    else if type(event) <> "roUrlEvent"
        m.top.result = {error: "Unexpected server response."}
    else if event.GetResponseCode() <> 200
        m.top.result = {error: "Could not open the catalog (HTTP " + event.GetResponseCode().ToStr() + ")."}
    else
        m.top.result = {catalog: ParseJson(event.GetString())}
    end if
end sub
