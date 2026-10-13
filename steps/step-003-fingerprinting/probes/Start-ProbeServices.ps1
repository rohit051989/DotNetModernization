<#
.SYNOPSIS
  Runs the services the WCF client matrix probe calls
  (29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md C11).

.DESCRIPTION
  ProbeServices hosts the WCF sample's own service types, loaded from a copy of
  the sample (never the registered repository), on the sample's bindings:

    net.tcp://localhost:8101/Utility      netTcp Transport/None         (Catalog.Host)
    net.tcp://localhost:8202/Account      netTcp Transport/Certificate  (Catalog.Host, mutual TLS)
    https://localhost:44301/Utility.svc   basicHttp Transport/None      (Hosting.Iis)
    https://localhost:44302/Utility.svc   the same, client certificate required (basicHttps Transport/Certificate)
    https://localhost:44301/Account.svc   wsHttp TransportWithMessageCredential/Certificate (Hosting.Iis)

  Certificates come only from files in -Certs, written by
  'WcfClientProbe make-certificates': no certificate store, no trust setting, no
  http.sys certificate binding, no URL reservation, no admin rights. HTTPS is a TLS
  terminator in front of plain http://localhost:8601 (see ProbeServices/Program.cs).

  wcf-backend's FundsTransferWS (basicHttp None, port 8090) is started separately,
  by WCF-backend\scripts\Start-FundsTransferWS.ps1 in the copy: plain HTTP, no
  certificates.

.EXAMPLE
  .\Start-ProbeServices.ps1 -ServicesBin ..\..\..\backend\runs\probes\wcf-sample\WCF\src\Hosting.Iis\bin -Certs ..\..\..\backend\runs\probes\certs
#>
param(
    [Parameter(Mandatory)] [string] $ServicesBin,
    [Parameter(Mandatory)] [string] $Certs,
    [string] $Output = (Join-Path $PSScriptRoot '..\..\..\backend\runs\probes\ProbeServices')
)
$ErrorActionPreference = 'Stop'
dotnet build (Join-Path $PSScriptRoot 'ProbeServices\ProbeServices.csproj') -c Release -o $Output --nologo -v quiet
if ($LASTEXITCODE -ne 0) { throw 'building ProbeServices failed' }
& (Join-Path $Output 'ProbeServices.exe') --services-bin (Resolve-Path $ServicesBin).Path --certs (Resolve-Path $Certs).Path
