#!/usr/bin/env python3
import os, sys, time, json
from mininet.log import setLogLevel, info
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.link import TCLink
from mininet.net import Mininet
from mininet.cli import CLI

RESULTS_DIR = "/tmp/fanet_results"

def build_topology():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    setLogLevel("info")
    info("*** FANET LB-MCR (Mininet) baslatiliyor...\n")

    net = Mininet(controller=RemoteController,
                  switch=OVSKernelSwitch,
                  link=TCLink, autoSetMacs=True)

    c0 = net.addController("c0", controller=RemoteController,
                           ip="127.0.0.1", port=6633)

    uavs = []
    for i in range(1,6):
        uavs.append(net.addHost(f"uav{i}", ip=f"10.0.0.{i}/8"))

    ugvs = []
    for i in range(1,3):
        ugvs.append(net.addHost(f"ugv{i}", ip=f"10.0.0.{10+i}/8"))

    s1 = net.addSwitch("s1", protocols="OpenFlow13")

    for uav in uavs:
        net.addLink(uav, s1, bw=54, delay="5ms", loss=2)
    for ugv in ugvs:
        net.addLink(ugv, s1, bw=100, delay="2ms", loss=0)

    net.start()
    time.sleep(2)

    info("\n*** Ping testi (uav1->ugv1)...\n")
    info(uavs[0].cmd(f"ping -c 3 10.0.0.11") + "\n")

    info("*** iperf3 throughput testi...\n")
    ugvs[0].cmd("iperf3 -s -D -p 5201")
    time.sleep(1)
    results = []
    for uav in uavs:
        out = uav.cmd(f"iperf3 -c 10.0.0.11 -p 5201 -t 10 -J 2>/dev/null")
        try:
            d = json.loads(out)
            bw = d["end"]["sum_received"]["bits_per_second"]/1e6
            info(f"    {uav.name}: {bw:.2f} Mbps\n")
            results.append({"src":uav.name,"bw_mbps":round(bw,3)})
        except:
            info(f"    {uav.name}: olcum hatasi\n")
    ugvs[0].cmd("pkill iperf3")

    info("*** RTT ping testi...\n")
    for uav in uavs:
        out = uav.cmd("ping -c 20 -i 0.1 10.0.0.11 2>/dev/null")
        rtt, loss = 0.0, 0.0
        for line in out.split("\n"):
            if "rtt" in line.lower():
                try: rtt = float(line.split("/")[4])
                except: pass
            if "packet loss" in line:
                try: loss = float(line.split("%")[0].split()[-1])
                except: pass
        info(f"    {uav.name}: RTT={rtt:.2f}ms loss={loss:.1f}%\n")
        results.append({"src":uav.name,"rtt_ms":rtt,"loss_pct":loss})

    with open(f"{RESULTS_DIR}/performance.json","w") as f:
        json.dump(results, f, indent=2)
    info(f"\n*** Sonuclar kaydedildi: {RESULTS_DIR}/performance.json\n")

    CLI(net)
    net.stop()

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("sudo python3 mininet_fanet_fixed.py")
        sys.exit(1)
    build_topology()
