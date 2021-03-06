#!/usr/bin/env python
# 2020 March 1 - modified and adapted for robot by Tal G. Ball,
# Maintaining Apache License, Version 2 and Amazon's Copyright Notice

# Copyright 2010-2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
#  http://aws.amazon.com/apache2.0
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.



import argparse
from awscrt import auth, io, mqtt, http
from awsiot import iotshadow
from awsiot import mqtt_connection_builder
from concurrent.futures import Future
import sys
import threading
import multiprocessing
import traceback
import time
import queue
import logging


# - Overview -
# This sample uses the AWS IoT Device Shadow Service to keep a property in
# sync between device and server. Imagine a light whose color may be changed
# through an app, or set by a local user.
#
# - Instructions -
# Once connected, type a value in the terminal and press Enter to update
# the property's "reported" value. The sample also responds when the "desired"
# value changes on the server. To observe this, edit the Shadow document in
# the AWS Console and set a new "desired" value.
#
# - Detail -
# On startup, the sample requests the shadow document to learn the property's
# initial state. The sample also subscribes to "delta" events from the server,
# which are sent when a property's "desired" value differs from its "reported"
# value. When the sample learns of a new desired value, that value is changed
# on the device and an update is sent to the server with the new "reported"
# value.


parser = argparse.ArgumentParser(description="Device Shadow sample keeps a property in sync across client and server")
parser.add_argument('--endpoint', required=True, help="Your AWS IoT custom endpoint, not including a port. " +
                                                      "Ex: \"w6zbse3vjd5b4p-ats.iot.us-west-2.amazonaws.com\"")
parser.add_argument('--cert',  help="File path to your client certificate, in PEM format")
parser.add_argument('--key', help="File path to your private key file, in PEM format")
parser.add_argument('--root-ca', help="File path to root certificate authority, in PEM format. " +
                                      "Necessary if MQTT server uses a certificate that's not already in " +
                                      "your trust store")
parser.add_argument('--client-id', default='samples-client-id', help="Client ID for MQTT connection.")
parser.add_argument('--thing-name', required=True, help="The name assigned to your IoT Thing")
parser.add_argument('--shadow-property', default="telemetry", help="Name of property in shadow to keep in sync")
parser.add_argument('--use-websocket', default=False, action='store_true',
    help="To use a websocket instead of raw mqtt. If you " +
    "specify this option you must specify a region for signing, you can also enable proxy mode.")
parser.add_argument('--signing-region', default='us-east-1', help="If you specify --use-web-socket, this " +
    "is the region that will be used for computing the Sigv4 signature")
parser.add_argument('--proxy-host', help="Hostname for proxy to connect to. Note: if you use this feature, " +
    "you will likely need to set --root-ca to the ca for your proxy.")
parser.add_argument('--proxy-port', type=int, default=8080, help="Port for proxy to connect to.")
parser.add_argument('--verbosity', choices=[x.name for x in io.LogLevel], default=io.LogLevel.NoLogs.name,
    help='Logging level')
parser.add_argument('--robot-url', required=True, help="Robot url for retrieving the telemetry")
parser.add_argument('--robot-ca', required=True, help="Root certificate for robot telemetry")

# Tal G. Ball - heavily reorganizing to support multiprocessing

proc_name = multiprocessing.current_process().name
# print("Process Name in shadow is %s" % proc_name)

SHADOW_VALUE_DEFAULT = "off"


class LockedData(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.shadow_value = None
        self.disconnect_called = False
        self.stop = False


class ShadowOps(object):
    def __init__(self, args, shadow_command_q):
        self.args = args
        self.shadow_command_q = shadow_command_q
        print("Initializing shadow operations")
        logging.info("Initializing shadow operations")

        if not args.verbosity:
            args.verbosity = io.LogLevel.NoLogs.name
        io.init_logging(getattr(io.LogLevel, args.verbosity), 'stderr')
        print("Set aws logging to %s" % args.verbosity)
        logging.info("Set aws logging to %s" % args.verbosity)

        self.mqtt_connection = None
        self.shadow_client = None
        self.robot_client = args.robot_client
        self.thing_name = args.thing_name
        self.shadow_property = args.shadow_property
        self.telemetry_thread = None

        self.is_sample_done = threading.Event()
        self.locked_data = LockedData()

        self.shadow_command_thread = threading.Thread(target=self.wait_to_end_shadow,
                                                      name="Shadow Command Thread")

        logging.debug("Starting Shadow Command Thread")
        self.shadow_command_thread.start()

        # logging.debug("Starting Shadow Operations Main")
        self.main(self.args)


    # Function for gracefully quitting this sample
    def exit(self, msg_or_exception):
        if isinstance(msg_or_exception, Exception):
            logging.debug("Exiting sample due to exception.")
            traceback.print_exception(msg_or_exception.__class__, msg_or_exception, sys.exc_info()[2])
        else:
            logging.debug("Exiting sample:", msg_or_exception)

        with self.locked_data.lock:
            if not self.locked_data.disconnect_called:
                print("Disconnecting...")
                logging.info("Disconnecting...")
                self.locked_data.disconnect_called = True
                future = self.mqtt_connection.disconnect()
                future.add_done_callback(self.on_disconnected)
                self.args.robot_client.post("Shutdown")

    def on_disconnected(self, disconnect_future):
        # type: (Future) -> None
        print("Disconnected.")
        logging.debug("Disconnected.")

        # Signal that sample is finished
        self.is_sample_done.set()


    def on_get_shadow_accepted(self, response):
        # type: (iotshadow.GetShadowResponse) -> None
        try:
            # logging.debug("Finished getting initial shadow state.")

            with self.locked_data.lock:
                if self.locked_data.shadow_value is not None:
                    # logging.debug("  Ignoring initial query because a delta event has already been received.")
                    return

            if response.state:
                if response.state.delta:
                    value = response.state.delta.get(self.shadow_property)
                    if value:
                        logging.debug("  Shadow contains delta value '{}'.".format(value))
                        self.change_shadow_value(value)
                        return

                if response.state.reported:
                    value = response.state.reported.get(self.shadow_property)
                    if value:
                        logging.debug("  Shadow contains reported value '{}'.".format(value))
                        self.set_local_value_due_to_initial_query(response.state.reported[self.shadow_property])
                        return

            logging.debug("  Shadow document lacks '{}' property. Setting defaults...".format(self.shadow_property))
            self.change_shadow_value(SHADOW_VALUE_DEFAULT)
            return

        except Exception as e:
            self.exit(e)


    def on_get_shadow_rejected(self, error):
        # type: (iotshadow.ErrorResponse) -> None
        if error.code == 404:
            logging.debug("Thing has no shadow document. Creating with defaults...")
            self.change_shadow_value(SHADOW_VALUE_DEFAULT)
        else:
            self.exit("Get request was rejected. code:{} message:'{}'".format(
                error.code, error.message))


    def on_shadow_delta_updated(self, delta):
        # type: (iotshadow.ShadowDeltaUpdatedEvent) -> None
        try:
            logging.debug("Received shadow delta event.")
            if delta.state and (self.shadow_property in delta.state):
                value = delta.state[self.shadow_property]
                if value is None:
                    logging.debug("  Delta reports that '{}' was deleted. Resetting defaults...".format(self.shadow_property))
                    self.change_shadow_value(SHADOW_VALUE_DEFAULT)
                    return
                else:
                    logging.debug("  Delta reports that desired value is '{}'. Changing local value...".format(value))
                    self.change_shadow_value(value)
            else:
                logging.debug("  Delta did not report a change in '{}'".format(self.shadow_property))

        except Exception as e:
            self.exit(e)


    def on_publish_update_shadow(self, future):
        #type: (Future) -> None
        try:
            future.result()
            logging.debug("Update request published.")
        except Exception as e:
            logging.debug("Failed to publish update request.")
            self.exit(e)


    def on_update_shadow_accepted(self, response):
        # type: (iotshadow.UpdateShadowResponse) -> None
        try:
            logging.debug("Finished updating reported shadow value to '{}'.".format(response.state.reported[self.shadow_property])) # type: ignore
            # print("Enter desired value: ") # remind user they can input new values
        except:
            self.exit("Updated shadow is missing the target property.")


    def on_update_shadow_rejected(self, error):
        # type: (iotshadow.ErrorResponse) -> None
        self.exit("Update request was rejected. code:{} message:'{}'".format(
            error.code, error.message))


    def set_local_value_due_to_initial_query(self, reported_value):
        with self.locked_data.lock:
            self.locked_data.shadow_value = reported_value
        # print("Enter desired value: ") # remind user they can input new values


    def change_shadow_value(self,value):
        with self.locked_data.lock:
            if self.locked_data.shadow_value == value:
                logging.debug("Local value is already '{}'.".format(value))
                # print("Enter desired value: ") # remind user they can input new values
                return

            logging.debug("Changed local shadow value to '{}'.".format(value))
            self.locked_data.shadow_value = value

        logging.debug("Updating reported shadow value to '{}'...".format(value))
        request = iotshadow.UpdateShadowRequest(
            thing_name=self.thing_name,
            state=iotshadow.ShadowState(
                reported={ self.shadow_property: value },
                desired={ self.shadow_property: value },
            )
        )
        future = self.shadow_client.publish_update_shadow(request, mqtt.QoS.AT_LEAST_ONCE)
        future.add_done_callback(self.on_publish_update_shadow)


    def user_input_thread_fn(self):
        while True:
            try:
                # Read user input
                try:
                    new_value = input() # python 2 only
                except NameError:
                    new_value = eval(input()) # python 3 only

                # If user wants to quit sample, then quit.
                # Otherwise change the shadow value.
                if new_value in ['exit', 'quit']:
                    self.exit("User has quit")
                    break
                else:
                    self.change_shadow_value(new_value)

            except Exception as e:
                logging.debug("Exception on input thread.")
                self.exit(e)
                break


    def get_robot_telemetry(self, robot_url=None, ca=None):
        while True:
            if self.locked_data.stop == True:
                # print("Calling exit from telemetry thread")
                # print("Live Threads:\n\t")
                # print("%s" % threading.enumerate())

                self.exit('Shutting down shadow updates')
                break

            try:
                response = self.robot_client.get()

                if response:
                    self.change_shadow_value(response[0])

            except Exception as e:
                logging.debug("Exception on getting telemetry")
                self.exit(e)
                break

            time.sleep(5.0)


    def wait_to_end_shadow(self):
        # print("Patiently waiting to end shadow operations")
        while True:
            task = self.shadow_command_q.get()
            if task == "Shutdown":
                with self.locked_data.lock:
                    self.locked_data.stop = True
                # logging.debug("Shadow stop signaled")
                self.shadow_command_q.task_done()
                break
            else:
                self.shadow_command_q.task_done()
        return


    def main(self, args):
        # logging.debug("Spinning up Shadow awsiot resources")
        event_loop_group = io.EventLoopGroup(1)
        host_resolver = io.DefaultHostResolver(event_loop_group)
        client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)
        # logging.debug("Shadow resources up")

        if args.use_websocket == True:
            proxy_options = None
            if (args.proxy_host):
                proxy_options = http.HttpProxyOptions(host_name=args.proxy_host, port=args.proxy_port)

            credentials_provider = auth.AwsCredentialsProvider.new_default_chain(client_bootstrap)
            self.mqtt_connection = mqtt_connection_builder.websockets_with_default_aws_signing(
                endpoint=args.endpoint,
                client_bootstrap=client_bootstrap,
                region=args.signing_region,
                credentials_provider=credentials_provider,
                websocket_proxy_options=proxy_options,
                ca_filepath=args.root_ca,
                client_id=args.client_id,
                clean_session=False,
                keep_alive_secs=6)

        else:
            # attrs = vars(args)
            # print(', '.join("%s: %s" % item for item in list(attrs.items())))
            self.mqtt_connection = mqtt_connection_builder.mtls_from_path(
                endpoint=args.endpoint,
                cert_filepath=args.cert,
                pri_key_filepath=args.key,
                client_bootstrap=client_bootstrap,
                ca_filepath=args.root_ca,
                client_id=args.client_id,
                clean_session=False,
                keep_alive_secs=6)

        print("Connecting to {} with client ID '{}'...".format(
            args.endpoint, args.client_id))
        logging.debug("Connecting to {} with client ID '{}'...".format(
            args.endpoint, args.client_id))

        connected_future = self.mqtt_connection.connect()

        self.shadow_client = iotshadow.IotShadowClient(self.mqtt_connection)

        # Wait for connection to be fully established.
        # Note that it's not necessary to wait, commands issued to the
        # mqtt_connection before its fully connected will simply be queued.
        # But this sample waits here so it's obvious when a connection
        # fails or succeeds.
        connected_future.result()
        print("Connected!")
        logging.debug("Connected!")

        try:
            # Subscribe to necessary topics.
            # Note that is **is** important to wait for "accepted/rejected" subscriptions
            # to succeed before publishing the corresponding "request".
            # print("Subscribing to Delta events...")
            delta_subscribed_future, _ = self.shadow_client.subscribe_to_shadow_delta_updated_events(
                request=iotshadow.ShadowDeltaUpdatedSubscriptionRequest(args.thing_name),
                qos=mqtt.QoS.AT_LEAST_ONCE,
                callback=self.on_shadow_delta_updated)

            # Wait for subscription to succeed
            delta_subscribed_future.result()

            # print("Subscribing to Update responses...")
            update_accepted_subscribed_future, _ = self.shadow_client.subscribe_to_update_shadow_accepted(
                request=iotshadow.UpdateShadowSubscriptionRequest(args.thing_name),
                qos=mqtt.QoS.AT_LEAST_ONCE,
                callback=self.on_update_shadow_accepted)

            update_rejected_subscribed_future, _ = self.shadow_client.subscribe_to_update_shadow_rejected(
                request=iotshadow.UpdateShadowSubscriptionRequest(args.thing_name),
                qos=mqtt.QoS.AT_LEAST_ONCE,
                callback=self.on_update_shadow_rejected)

            # Wait for subscriptions to succeed
            update_accepted_subscribed_future.result()
            update_rejected_subscribed_future.result()

            # print("Subscribing to Get responses...")
            get_accepted_subscribed_future, _ = self.shadow_client.subscribe_to_get_shadow_accepted(
                request=iotshadow.GetShadowSubscriptionRequest(args.thing_name),
                qos=mqtt.QoS.AT_LEAST_ONCE,
                callback=self.on_get_shadow_accepted)

            get_rejected_subscribed_future, _ = self.shadow_client.subscribe_to_get_shadow_rejected(
                request=iotshadow.GetShadowSubscriptionRequest(args.thing_name),
                qos=mqtt.QoS.AT_LEAST_ONCE,
                callback=self.on_get_shadow_rejected)

            # Wait for subscriptions to succeed
            get_accepted_subscribed_future.result()
            get_rejected_subscribed_future.result()

            # The rest of the sample runs asyncronously.

            # Issue request for shadow's current state.
            # The response will be received by the on_get_accepted() callback
            # print("Requesting current shadow state...")
            publish_get_future = self.shadow_client.publish_get_shadow(
                request=iotshadow.GetShadowRequest(args.thing_name),
                qos=mqtt.QoS.AT_LEAST_ONCE)

            # Ensure that publish succeeds
            publish_get_future.result()

            # Launch thread to handle user input.
            # A "daemon" thread won't prevent the program from shutting down.
            # print("Launching thread to read user input...")
            # user_input_thread = threading.Thread(target=user_input_thread_fn, name='user_input_thread')
            # user_input_thread.daemon = True
            # user_input_thread.start()

            # Launch thread to send telemetry updates to shadow
            self.telemetry_thread = threading.Thread(
                target=self.get_robot_telemetry,
                name='Robot Telemetry Thread',
                args=(args.robot_url, args.robot_ca)
            )
            # self.telemetry_thread.daemon = True
            self.telemetry_thread.start()

        except Exception as e:
            self.exit(e)

        # Wait for the sample to finish (user types 'quit', or an error occurs)
        self.is_sample_done.wait()


if __name__ == '__main__':
    # Process input args
    args = parser.parse_args()
    sq = queue.Queue()

    s = ShadowOps(args, sq)