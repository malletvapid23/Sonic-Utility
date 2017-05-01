#! /usr/bin/python -u

import os
import re
import sys
import stat
import time
import click
import urllib
import shutil
import subprocess

HOST_PATH = '/host'
IMAGE_PREFIX = 'SONiC-OS-'
IMAGE_DIR_PREFIX = 'image-'
ONIE_DEFAULT_IMAGE_PATH = '/tmp/sonic_image'
ABOOT_DEFAULT_IMAGE_PATH = '/tmp/sonic_image.swi'
IMAGE_TYPE_ABOOT = 'aboot'
IMAGE_TYPE_ONIE = 'onie'
ABOOT_BOOT_CONFIG = '/boot-config'

def reporthook(count, block_size, total_size):
    global start_time
    if count == 0:
        start_time = time.time()
        return

    duration = time.time() - start_time
    progress_size = int(count * block_size)
    speed = int(progress_size / (1024 * duration))
    percent = int(count * block_size * 100 / total_size)
    sys.stdout.write("\r...%d%%, %d MB, %d KB/s, %d seconds passed" %
                                  (percent, progress_size / (1024 * 1024), speed, duration))
    sys.stdout.flush()

def get_image_type():
    cmdline = open('/proc/cmdline', 'r')
    if "Aboot=" in cmdline.read():
        return IMAGE_TYPE_ABOOT
    return IMAGE_TYPE_ONIE

# Run bash command and print output to stdout
def run_command(command, pager=False):
    click.echo(click.style("Command: ", fg='cyan') + click.style(command, fg='green'))
    p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
    if pager is True:
        click.echo_via_pager(p.stdout.read())
    else:
        click.echo(p.stdout.read())
    p.wait()
    if p.returncode != 0:
        sys.exit(p.returncode)

# Returns list of installed images
def get_installed_images():
    images = []
    if get_image_type() == IMAGE_TYPE_ABOOT:
        for filename in os.listdir(HOST_PATH):
            if filename.startswith(IMAGE_DIR_PREFIX):
                images.append(filename.replace(IMAGE_DIR_PREFIX, IMAGE_PREFIX))
    else:
        config = open(HOST_PATH + '/grub/grub.cfg', 'r')
        for line in config:
            if line.startswith('menuentry'):
                image = line.split()[1].strip("'")
                if IMAGE_PREFIX in image:
                    images.append(image)
        config.close()
    return images


# Returns name of current image
def get_current_image():
    cmdline = open('/proc/cmdline', 'r')
    current = re.search("loop=(\S+)/fs.squashfs", cmdline.read()).group(1)
    cmdline.close()
    return current.replace(IMAGE_DIR_PREFIX, IMAGE_PREFIX)

# Returns name of next boot image
def get_next_image():
    if get_image_type() == IMAGE_TYPE_ABOOT:
        config = open(HOST_PATH + ABOOT_BOOT_CONFIG, 'r')
        next_image = re.search("SWI=flash:(\S+)/", config.read()).group(1).replace(IMAGE_DIR_PREFIX, IMAGE_PREFIX)
        config.close()
    else:
        images = get_installed_images()
        grubenv = subprocess.check_output(["/usr/bin/grub-editenv", HOST_PATH + "/grub/grubenv", "list"])
        m = re.search("next_entry=(\d+)", grubenv)
        if m:
            next_image_index = int(m.group(1))
        else:
            m = re.search("saved_entry(\d+)", grubenv)
            if m:
                next_image_index = int(m.group(1))
            else:
                next_image_index = 0
        next_image = images[next_image_index]
    return next_image

# Callback for confirmation prompt. Aborts if user enters "n"
def abort_if_false(ctx, param, value):
    if not value:
        ctx.abort()


# Main entrypoint
@click.group()
def cli():
    """ SONiC image installation manager """
    if os.geteuid() != 0:
        exit("Root privileges required for this operation")


# Install image
@cli.command()
@click.option('-y', '--yes', is_flag=True, callback=abort_if_false,
        expose_value=False, prompt='New image will be installed, continue?')
@click.argument('url')
def install(url):
    """ Install image from local binary or URL"""
    cleanup_image = False
    if get_image_type() == IMAGE_TYPE_ABOOT:
        DEFAULT_IMAGE_PATH = ABOOT_DEFAULT_IMAGE_PATH
    else:
        DEFAULT_IMAGE_PATH = ONIE_DEFAULT_IMAGE_PATH

    if url.startswith('http://') or url.startswith('https://'):
        click.echo('Downloading image...')
        urllib.urlretrieve(url, DEFAULT_IMAGE_PATH, reporthook)
        image_path = DEFAULT_IMAGE_PATH
    else:
        image_path = os.path.join("./", url)

    if get_image_type() == IMAGE_TYPE_ABOOT:
        run_command("/usr/bin/unzip -od /tmp %s boot0" % image_path)
        run_command("swipath=%s target_path=/host sonic_upgrade=1 . /tmp/boot0" % image_path)
    else:
        os.chmod(image_path, stat.S_IXUSR)
        run_command(image_path)
        run_command("cp /etc/sonic/minigraph.xml /host/")
        run_command('grub-set-default --boot-directory=' + HOST_PATH + ' 0')
    click.echo('Done')


# List installed images
@cli.command()
def list():
    """ Print installed images """
    images = get_installed_images()
    curimage = get_current_image()
    nextimage = get_next_image()
    click.echo("Current: " + curimage)
    click.echo("Next: " + nextimage)
    click.echo("Available: ")
    for image in get_installed_images():
        click.echo(image)

# Set default image for boot
@cli.command()
@click.argument('image')
def set_default(image):
    """ Choose image to boot from by default """
    images = get_installed_images()
    if image not in images:
        click.echo('Image does not exist')
        sys.exit(1)
    if get_image_type() == IMAGE_TYPE_ABOOT:
        image_dir = image.replace(IMAGE_PREFIX, IMAGE_DIR_PREFIX)
        command = "echo \"SWI=flash:%s/.sonic-boot.swi\" > %s/%s" % (image_dir, HOST_PATH, ABOOT_BOOT_CONFIG)
    else:
        command = 'grub-set-default --boot-directory=' + HOST_PATH + ' ' + str(images.index(image))
    run_command(command)


# Set image for next boot
@cli.command()
@click.argument('image')
def set_next_boot(image):
    """ Choose image for next reboot (one time action) """
    images = get_installed_images()
    if image not in images:
        click.echo('Image does not exist')
        sys.exit(1)
    if get_image_type() == IMAGE_TYPE_ABOOT:
        image_dir = image.replace(IMAGE_PREFIX, IMAGE_DIR_PREFIX)
        command = "echo \"SWI=flash:%s/.sonic-boot.swi\" > %s/%s" % (image_dir, HOST_PATH, ABOOT_BOOT_CONFIG)
    else:
        command = 'grub-reboot --boot-directory=' + HOST_PATH + ' ' + str(images.index(image))
    run_command(command)


# Uninstall image
@cli.command()
@click.option('-y', '--yes', is_flag=True, callback=abort_if_false,
        expose_value=False, prompt='Image will be removed, continue?')
@click.argument('image')
def remove(image):
    """ Uninstall image """
    images = get_installed_images()
    current = get_current_image()
    nextimage = get_next_image()
    if image not in images:
        click.echo('Image does not exist')
        sys.exit(1)
    if image == current:
        click.echo('Cannot remove current image')
        sys.exit(1)

    if get_image_type() == IMAGE_TYPE_ABOOT:
        if image == nextimage:
            image_dir = current.replace(IMAGE_PREFIX, IMAGE_DIR_PREFIX)
            command = "echo \"SWI=flash:%s/.sonic-boot.swi\" > %s/%s" % (image_dir, HOST_PATH, ABOOT_BOOT_CONFIG)
            run_command(command)
            click.echo("Set next boot to current image %s" % current)

        image_dir = image.replace(IMAGE_PREFIX, IMAGE_DIR_PREFIX)
        click.echo('Removing image root filesystem...')
        shutil.rmtree(HOST_PATH + '/' + image_dir)
        click.echo('Image removed')
    else:
        click.echo('Updating GRUB...')
        config = open(HOST_PATH + '/grub/grub.cfg', 'r')
        old_config = config.read()
        menuentry = re.search("menuentry '" + image + "[^}]*}", old_config).group()
        config.close()
        config = open(HOST_PATH + '/grub/grub.cfg', 'w')
        # remove menuentry of the image in grub.cfg
        config.write(old_config.replace(menuentry, ""))
        config.close()
        click.echo('Done')

        image_dir = image.replace(IMAGE_PREFIX, IMAGE_DIR_PREFIX)
        click.echo('Removing image root filesystem...')
        shutil.rmtree(HOST_PATH + '/' + image_dir)
        click.echo('Done')

        run_command('grub-set-default --boot-directory=' + HOST_PATH + ' 0')
        click.echo('Image removed')

if __name__ == '__main__':
    cli()
