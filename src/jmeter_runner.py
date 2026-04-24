"""
jmeter_runner.py
Runs a JMeter .jmx script locally (via subprocess) or on AWS EC2 (via boto3).
Public functions:
    run_local(jmx_path, output_dir)        -> str (path to .jtl file)
    run_on_aws(jmx_path, output_dir, cfg)  -> str (path to downloaded .jtl)
"""

import subprocess
import os
import time
import shutil
from pathlib import Path


# ── Local JMeter runner ────────────────────────────────────────────────────────

def run_local(jmx_path: str, output_dir: str = "output") -> str:
    """
    Run a JMeter .jmx file locally using the JMeter CLI.
    Requires JMeter to be installed and on PATH (or JMETER_PATH env var set).

    Returns the path to the generated .jtl results file.
    """
    jmeter_bin = os.environ.get("JMETER_PATH", "jmeter")
    jtl_path = os.path.join(output_dir, "results.jtl")
    log_path = os.path.join(output_dir, "jmeter.log")

    os.makedirs(output_dir, exist_ok=True)

    cmd = [
        jmeter_bin,
        "-n",                   # non-GUI mode
        "-t", jmx_path,         # test plan
        "-l", jtl_path,         # results file
        "-j", log_path,         # JMeter log
        "-e",                   # generate HTML report
        "-o", os.path.join(output_dir, "html_report"),
    ]

    print(f"Running: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=3600,  # max 1 hour
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"JMeter failed (exit {result.returncode}):\n"
            f"STDOUT: {result.stdout[-2000:]}\n"
            f"STDERR: {result.stderr[-2000:]}"
        )

    if not os.path.exists(jtl_path):
        raise FileNotFoundError(f"JMeter ran but no .jtl file found at {jtl_path}")

    return jtl_path


# ── AWS EC2 JMeter runner ──────────────────────────────────────────────────────

def run_on_aws(jmx_path: str, output_dir: str = "output", cfg: dict = None) -> str:
    """
    Spin up an EC2 instance, upload the JMX, run JMeter, download results, terminate.

    cfg keys:
        region         (str)  default: eu-west-1
        instance_type  (str)  default: t3.medium
        ami_id         (str)  Amazon Linux 2 AMI (region-specific)
        key_name       (str)  EC2 key pair name (must exist in your AWS account)
        security_group (str)  SG that allows SSH from your IP

    Returns the path to the downloaded .jtl file.
    """
    try:
        import boto3
        import paramiko
    except ImportError:
        raise ImportError(
            "boto3 and paramiko are required for AWS runs. "
            "Install them with: pip install boto3 paramiko"
        )

    cfg = cfg or {}
    region         = cfg.get("region", os.environ.get("AWS_DEFAULT_REGION", "eu-west-1"))
    instance_type  = cfg.get("instance_type", "t3.medium")
    key_name       = cfg.get("key_name", "perfai-key")
    security_group = cfg.get("security_group", "perfai-sg")

    ec2 = boto3.resource("ec2", region_name=region)
    ec2_client = boto3.client("ec2", region_name=region)

    # Find latest Amazon Linux 2 AMI
    ami_id = cfg.get("ami_id") or _get_latest_al2_ami(ec2_client)

    print(f"Launching EC2 instance ({instance_type}) in {region}...")
    instances = ec2.create_instances(
        ImageId=ami_id,
        InstanceType=instance_type,
        MinCount=1,
        MaxCount=1,
        KeyName=key_name,
        SecurityGroups=[security_group],
        UserData=_ec2_userdata(),
        TagSpecifications=[{
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": "perfai-runner"}],
        }],
    )
    instance = instances[0]

    try:
        print("Waiting for instance to be running...")
        instance.wait_until_running()
        instance.reload()
        public_ip = instance.public_ip_address

        # Wait for SSH + JMeter install to finish
        print("Waiting 90s for instance setup (JMeter install via UserData)...")
        time.sleep(90)

        key_path = cfg.get("key_path", f"{key_name}.pem")
        _run_remote_test(public_ip, key_path, jmx_path, output_dir)

    finally:
        print("Terminating EC2 instance...")
        instance.terminate()

    return os.path.join(output_dir, "results.jtl")


def run_distributed(
    jmx_path: str,
    output_dir: str = "output",
    cfg: dict = None,
    agent_count: int = 2,
) -> str:
    """
    Run a distributed JMeter test across multiple EC2 agent instances.

    Spins up `agent_count` EC2 worker nodes, configures the controller to use
    them as remote engines, runs the test from a separate controller instance,
    then downloads and merges results.

    cfg keys (same as run_on_aws plus):
        agent_count     (int)  number of agent EC2 instances  (overrides param)
        controller_type (str)  default: t3.medium
        agent_type      (str)  default: t3.large

    Returns the path to the merged .jtl file.
    """
    try:
        import boto3
        import paramiko
    except ImportError:
        raise ImportError(
            "boto3 and paramiko are required for distributed AWS runs. "
            "Install them with: pip install boto3 paramiko"
        )

    cfg = cfg or {}
    n_agents        = cfg.get("agent_count", agent_count)
    region          = cfg.get("region", os.environ.get("AWS_DEFAULT_REGION", "eu-west-1"))
    controller_type = cfg.get("controller_type", "t3.medium")
    agent_type      = cfg.get("agent_type", "t3.large")
    key_name        = cfg.get("key_name", "perfai-key")
    key_path        = cfg.get("key_path", f"{key_name}.pem")
    security_group  = cfg.get("security_group", "perfai-sg")

    ec2 = boto3.resource("ec2", region_name=region)
    ec2_client = boto3.client("ec2", region_name=region)
    ami_id = cfg.get("ami_id") or _get_latest_al2_ami(ec2_client)
    userdata = _ec2_userdata()

    print(f"Launching {n_agents} agent instance(s) and 1 controller ({region})...")

    # Launch agents
    agent_instances = ec2.create_instances(
        ImageId=ami_id,
        InstanceType=agent_type,
        MinCount=n_agents,
        MaxCount=n_agents,
        KeyName=key_name,
        SecurityGroups=[security_group],
        UserData=userdata,
        TagSpecifications=[{
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": "perfai-agent"}],
        }],
    )

    # Launch controller
    controller_instances = ec2.create_instances(
        ImageId=ami_id,
        InstanceType=controller_type,
        MinCount=1,
        MaxCount=1,
        KeyName=key_name,
        SecurityGroups=[security_group],
        UserData=userdata,
        TagSpecifications=[{
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": "perfai-controller"}],
        }],
    )
    controller = controller_instances[0]

    all_instances = agent_instances + controller_instances

    try:
        print("Waiting for all instances to be running...")
        for inst in all_instances:
            inst.wait_until_running()
            inst.reload()

        agent_ips = [inst.private_ip_address for inst in agent_instances]
        print(f"Agent private IPs: {agent_ips}")

        print("Waiting 120s for JMeter installation via UserData...")
        time.sleep(120)

        _run_distributed_test(
            controller_ip=controller.public_ip_address,
            agent_ips=agent_ips,
            key_path=key_path,
            jmx_path=jmx_path,
            output_dir=output_dir,
        )

    finally:
        print("Terminating all instances...")
        for inst in all_instances:
            inst.terminate()

    return os.path.join(output_dir, "results.jtl")


def _run_distributed_test(
    controller_ip: str,
    agent_ips: list[str],
    key_path: str,
    jmx_path: str,
    output_dir: str,
):
    import paramiko
    from scp import SCPClient

    remote_agents = ",".join(agent_ips)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(controller_ip, username="ec2-user", key_filename=key_path)

    # Upload the test plan
    with SCPClient(ssh.get_transport()) as scp:
        scp.put(jmx_path, "/home/ec2-user/test.jmx")

    # Run JMeter in distributed mode: controller directs agents via -R
    cmd = (
        f"/opt/apache-jmeter/bin/jmeter -n "
        f"-t /home/ec2-user/test.jmx "
        f"-R {remote_agents} "
        f"-l /home/ec2-user/results.jtl "
        f"-j /home/ec2-user/jmeter.log "
        f"-Djava.rmi.server.hostname={controller_ip}"
    )
    print(f"Distributed run command: {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=3600)
    exit_code = stdout.channel.recv_exit_status()
    if exit_code != 0:
        raise RuntimeError(
            f"Distributed JMeter run failed (exit {exit_code}): {stderr.read().decode()}"
        )

    os.makedirs(output_dir, exist_ok=True)
    with SCPClient(ssh.get_transport()) as scp:
        scp.get("/home/ec2-user/results.jtl", os.path.join(output_dir, "results.jtl"))

    ssh.close()


def _run_remote_test(host: str, key_path: str, jmx_path: str, output_dir: str):
    import paramiko
    from scp import SCPClient

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username="ec2-user", key_filename=key_path)

    with SCPClient(ssh.get_transport()) as scp:
        scp.put(jmx_path, "/home/ec2-user/test.jmx")

    stdin, stdout, stderr = ssh.exec_command(
        "/opt/apache-jmeter/bin/jmeter -n -t /home/ec2-user/test.jmx "
        "-l /home/ec2-user/results.jtl -j /home/ec2-user/jmeter.log"
    )
    exit_code = stdout.channel.recv_exit_status()
    if exit_code != 0:
        raise RuntimeError(f"Remote JMeter failed: {stderr.read().decode()}")

    os.makedirs(output_dir, exist_ok=True)
    with SCPClient(ssh.get_transport()) as scp:
        scp.get("/home/ec2-user/results.jtl", os.path.join(output_dir, "results.jtl"))

    ssh.close()


def _get_latest_al2_ami(ec2_client) -> str:
    response = ec2_client.describe_images(
        Owners=["amazon"],
        Filters=[
            {"Name": "name",         "Values": ["amzn2-ami-hvm-*-x86_64-gp2"]},
            {"Name": "state",        "Values": ["available"]},
            {"Name": "architecture", "Values": ["x86_64"]},
        ],
    )
    images = sorted(response["Images"], key=lambda x: x["CreationDate"], reverse=True)
    return images[0]["ImageId"]


def _ec2_userdata() -> str:
    """UserData script that installs Java and JMeter on the EC2 instance at boot."""
    return """#!/bin/bash
yum update -y
amazon-linux-extras install java-openjdk11 -y
JMETER_VERSION=5.6.3
cd /opt
wget -q https://downloads.apache.org/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.tgz
tar xzf apache-jmeter-${JMETER_VERSION}.tgz
mv apache-jmeter-${JMETER_VERSION} apache-jmeter
ln -s /opt/apache-jmeter/bin/jmeter /usr/local/bin/jmeter
echo "JMeter ready" >> /var/log/perfai-setup.log
"""
