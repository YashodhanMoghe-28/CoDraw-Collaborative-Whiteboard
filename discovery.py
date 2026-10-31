"""IPv4 LAN multicast discovery. HTTP heartbeats verify announcements."""
import asyncio
import json
import logging
import socket


class Discovery(asyncio.DatagramProtocol):
    def __init__(self, node):
        self.node = node
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        try:
            m = json.loads(data)
            if m.get('cluster') == self.node.args.cluster and m.get('id') != self.node.id:
                self.node.learn(m)
        except (ValueError, TypeError, KeyError):
            pass

    def announce(self):
        if self.transport:
            m = self.node.identity() | {'cluster': self.node.args.cluster}
            self.transport.sendto(json.dumps(m).encode(),
                                  (self.node.args.multicast, self.node.args.discovery_port))


async def start(node):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', node.args.discovery_port))
    interface = socket.inet_aton(node.args.interface)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                    socket.inet_aton(node.args.multicast) + interface)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    if node.args.interface != '0.0.0.0':
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, interface)
    sock.setblocking(False)
    transport, protocol = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: Discovery(node), sock=sock)
    logging.info('UDP discovery listening on %s:%d', node.args.multicast, node.args.discovery_port)
    return transport, protocol
