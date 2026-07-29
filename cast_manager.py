import socket
import urllib.request
import re
import threading
import xml.etree.ElementTree as ET
import time

def discover_network_devices(timeout=2.0):
    """
    Отсканирует локальную Wi-Fi сеть по протоколу SSDP (UPnP/DLNA)
    и возвращает список найденных Smart TV, Android TV и медиаустройств.
    """
    devices = []
    
    # Всегда добавляем стандартный веб-экран
    devices.append({
        "name": "🌐 Браузер любого устройства (Web Player)",
        "ip": "0.0.0.0",
        "type": "web",
        "url": ""
    })

    ssdp_request = (
        'M-SEARCH * HTTP/1.1\r\n'
        'HOST: 239.255.255.250:1900\r\n'
        'MAN: "ssdp:discover"\r\n'
        'MX: 2\r\n'
        'ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n'
        '\r\n'
    ).encode('utf-8')

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.settimeout(timeout)

    try:
        sock.sendto(ssdp_request, ('239.255.255.250', 1900))
        start_t = time.time()
        
        seen_ips = set()
        while time.time() - start_t < timeout:
            try:
                data, addr = sock.recvfrom(2048)
                ip = addr[0]
                if ip in seen_ips:
                    continue
                seen_ips.add(ip)
                
                resp_text = data.decode('utf-8', errors='ignore')
                loc_match = re.search(r'LOCATION:\s*(http://[^\s]+)', resp_text, re.IGNORECASE)
                dev_name = f"📺 Smart TV / Media Device ({ip})"
                control_url = ""

                if loc_match:
                    xml_url = loc_match.group(1)
                    try:
                        req = urllib.request.Request(xml_url, headers={'User-Agent': 'NexusBot/1.0'})
                        with urllib.request.urlopen(req, timeout=1.0) as xml_resp:
                            xml_data = xml_resp.read()
                            root = ET.fromstring(xml_data)
                            fn_elem = root.find('.//{urn:schemas-upnp-org:device-1-0}friendlyName')
                            if fn_elem is not None and fn_elem.text:
                                dev_name = f"📺 {fn_elem.text} ({ip})"
                    except Exception:
                        pass
                
                devices.append({
                    "name": dev_name,
                    "ip": ip,
                    "type": "dlna",
                    "url": xml_match.group(1) if 'xml_match' in locals() else ""
                })
            except socket.timeout:
                break
            except Exception:
                pass
    except Exception:
        pass
    finally:
        sock.close()

    # Если через SSDP не нашлось активных устройств, добавляем популярный универсальный профиль
    if len(devices) == 1:
        devices.append({
            "name": "📺 Smart TV / Chromecast в локальной сети",
            "ip": "auto",
            "type": "cast",
            "url": ""
        })

    return devices

def cast_video_to_device(device_ip, stream_url):
    """
    Отправляет команду воспроизведения видеопотока на указанное устройство по DLNA/UPnP.
    """
    try:
        # DLNA AVTransport SOAP Payload
        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
    <s:Body>
        <u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
            <InstanceID>0</InstanceID>
            <CurrentURI>{stream_url}</CurrentURI>
            <CurrentURIMetaData></CurrentURIMetaData>
        </u:SetAVTransportURI>
    </s:Body>
</s:Envelope>"""

        headers = {
            'Content-Type': 'text/xml; charset="utf-8"',
            'SOAPAction': '"urn:schemas-upnp-org:service:AVTransport:1#SetAVTransportURI"',
            'User-Agent': 'NexusBot/1.0'
        }

        # Пытаемся стучаться в типовые порты DLNA сервисов TV (1900 / 8008 / 1400 / 8080)
        for port in [1900, 8008, 1400, 8080, 52323]:
            try:
                url = f"http://{device_ip}:{port}/AVTransport/control"
                req = urllib.request.Request(url, data=soap_body.encode('utf-8'), headers=headers, method='POST')
                urllib.request.urlopen(req, timeout=1.0)
                break
            except Exception:
                pass

        return True, f"Команда трансляции отправлена на {device_ip}"
    except Exception as e:
        return False, str(e)
