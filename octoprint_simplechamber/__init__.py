# coding=utf-8
from __future__ import absolute_import
import octoprint.plugin
import octoprint.util
import copy
import os
import time
import RPi.GPIO as GPIO
from octoprint.events import Events

try:
	import adafruit_dht
except ImportError:
	pass

DHT_DRIVER_DTOVERLAY = 'dtoverlay'
DHT_DRIVER_ADAFRUIT_DHT = 'adafruit_dht'


class SimpleChamber(octoprint.plugin.StartupPlugin,
		    octoprint.plugin.RestartNeedingPlugin,
		    octoprint.plugin.SettingsPlugin,
		    octoprint.plugin.TemplatePlugin,
		    octoprint.plugin.EventHandlerPlugin,
		   ):

	sensor = None
	last_dht_temp = None
	pwm = None
	fan_speed = 0
	fan_int = 0
	gpio_board_mode = True
	max_temp = 0
	dht_iio_path = None
	dht_driver = None


	def get_gpio_pin(self, board_pin):
		if self.gpio_board_mode:
			return board_pin
		bcm_map = [-1, -1, 2, -1, 3, -1, 4, -1, -1, -1,
			   17, 18, 27, -1, 22, 23, -1, 24, 10, -1,
			   9, 25, 11, 8, -1, 7, -1, -1, 5, -1,
			   6, 12, 13, -1, 19, 16, 26, 20, -1, 21]
		if 1 <= board_pin <= 40:
			return bcm_map[board_pin - 1]
		return -1


	def get_settings_defaults(self):
		return dict(
			fan_enabled = True,
			dht_driver = DHT_DRIVER_DTOVERLAY, # DHT_DRIVER_ADAFRUIT_DHT,
			max_temp = 30,
			sensor_type = 22,
			sensor_pin = 23,
			fan_pin = 19
		)


	def get_settings_version(self):
		return 1


	def get_template_configs(self):
		return [
			dict(type="settings", name="Simple Chamber", custom_bindings=False)
		]


	def get_dht_iio_path(self):
		devices_path = '/sys/devices/platform'
		if not os.path.isdir(devices_path):
			return None
		dhts = [f for f in os.listdir(devices_path) if f.startswith('dht11')]
		if len(dhts) < 1:
			return None
		path = '%s/%s/iio:device0' % (devices_path, dhts[0])
		return path if os.path.isdir(path) else None


	def read_dht_iio_value(self, name):
		if self.dht_iio_path:
			try:
				with open('%s/in_%s_input' % (self.dht_iio_path, name), 'r') as f:
					return float(f.read())/1000.0
			except Exception as e:
				pass
		return None


	def setup_hardware(self):
		self.max_temp = float(self._settings.get(["max_temp"]))
		self.dht_driver = self._settings.get(["dht_driver"])

		fan_enabled = self._settings.get(["fan_enabled"])
		fan_pin = self.get_gpio_pin(self._settings.get(["fan_pin"]))
		sensor_pin = int(self._settings.get(["sensor_pin"]))
		sensor_type = int(self._settings.get(["sensor_type"]))

		self._logger.info(
			"Simple Chamber: sensor=DHT%d, pin=%d, fan=%d%s, max=%.2fC (%s)" % (
				sensor_type,
				sensor_pin,
				fan_pin,
				"" if fan_enabled else " (disabled)",
				self.max_temp,
				self.dht_driver))

		if self.pwm:
			self.pwm.stop()
		if self.sensor:
			self.sensor.exit()

		self.pwm = None
		if fan_enabled:
			GPIO.setup(fan_pin, GPIO.OUT)
			self.pwm = GPIO.PWM(fan_pin, 100)
			self.pwm.start(0)

		self.sensor = None
		self.dht_iio_path = self.get_dht_iio_path()

		if self.dht_driver == DHT_DRIVER_DTOVERLAY:
			if not self.dht_iio_path:
				self._logger.exception("Sensor error: no sensor detected by Device Tree Overlay")
			return

		if self.dht_driver != DHT_DRIVER_ADAFRUIT_DHT:
			self._logger.exception("Unknown sensor driver")
			return

		sensors = {
			11: adafruit_dht.DHT11,
			21: adafruit_dht.DHT21,
			22: adafruit_dht.DHT22
		}
		try:
			self.sensor = sensors[sensor_type](sensor_pin)
			# If sensor was initialized, try reading a temperature to ensure it's working
			try:
				_ = self.sensor.temperature
			except RuntimeError as e:
				# adafruit_dht doesn't return an error code, but a runtime exception.
				# Our only option is to check the content of the exception message.
				# If it's a retriable error, hardware is probably fine, otherwise log it.
				if "Try again" in str(e):
					pass
				else:
					raise e
		except Exception as e:
			self._logger.exception("Sensor error: %s" % str(e))
			pass


	def on_event(self, event, payload):
		if event == Events.SETTINGS_UPDATED:
			self.setup_hardware()
			return


	def on_after_startup(self):
		# Set GPIO to board numbering, if possible
		current_mode = GPIO.getmode()
		if current_mode is None:
			GPIO.setmode(GPIO.BOARD)
			self.gpio_board_mode = True
		elif current_mode != GPIO.BOARD:
			GPIO.setmode(current_mode)
			self.gpio_board_mode = False

		# DHTXX sensors are slow, sample every 2 seconds (DHT11 can be sampled every 1.5s)
		octoprint.util.RepeatedTimer(2.0, self.perform_tasks).start()

		self.setup_hardware()

		self._logger.info("Simple Chamber started")


	def get_update_information(self):
		return dict(
			simplechamber = dict(
				displayName = "Simple Chamber Plugin",
				displayVersion = self._plugin_version,
				type = "github_release",
				user = "adrcunha",
				repo = "OctoPrint-SimpleChamber",
				current = self._plugin_version,
				pip = "https://github.com/adrcunha/OctoPrint-SimpleChamber/archive/{target_version}.zip",
				dependency_links = False
			)
		)


	def get_temperature(self):
		temperature = None
		humidity = None
		for i in range(0, 2):
			try:
				if self.dht_driver == DHT_DRIVER_ADAFRUIT_DHT:
					if not self.sensor:
						return
					temperature = self.sensor.temperature
					humidity = self.sensor.humidity
				elif self.dht_driver == DHT_DRIVER_DTOVERLAY:
					if not self.dht_iio_path:
						return
					temperature = self.read_dht_iio_value('temp')
					humidity = self.read_dht_iio_value('humidityrelative')
				break
			except RuntimeError as e:
				self._logger.debug("Sensor reading error: %s" % str(e))
				pass
		# Skip if error (it's fine, the temperature just won't update in the graph)
		self._logger.debug("H=%s T=%s" % (humidity, temperature))
		if temperature is None:
			return
		# Ignore subtle drops in temperature.
		# https://github.com/adafruit/Adafruit_Python_DHT/blob/master/Adafruit_DHT/common.py#L65
		if self.last_dht_temp and temperature - self.last_dht_temp <= -2:
				return
		self.last_dht_temp = temperature


	def handle_fan(self):
		if not self.last_dht_temp or not self.pwm:
			return
		prev_speed = self.fan_speed
		self.fan_speed = self.get_fan_speed(self.last_dht_temp, self.max_temp)
		if prev_speed != self.fan_speed:
			self._logger.info("Temperature is %.2fC, target is %.2fC, fan is now at %d%%" % (self.last_dht_temp, self.max_temp, self.fan_speed))
		if self.fan_speed > 0:
			if (prev_speed < 50 and self.fan_speed < prev_speed) or (prev_speed == 0 and self.fan_speed < 50):
				# Slowing down fan when already at less than 50%, or starting from zero: "warm up" fan or it may stop
				self.pwm.ChangeDutyCycle(100)
				time.sleep(0.5)
		self.pwm.ChangeDutyCycle(self.fan_speed)


	# PI controller originally from Andreas Spiess
	# Details: https://en.wikipedia.org/wiki/PID_controller
	# for i in [11, 15, 27, 30, 31, 32, 33, 34, 34, 34, 33, 33, 33, 33, 32, 31, 30, 29, 30]:
	#   print(i, __plugin_implementation__.get_fan_speed(i, 30))
	# results in 0 0 0 0 22 53 83 100 100 100 86 87 88 88 59 29 0 0 0
	def get_fan_speed(self, temp, max_temp):
		d = temp - max_temp
		self.fan_int += d
		p = d * 30 # Kp
		i = self.fan_int * 0.2 # Ki
		self.fan_int = max(min(100.0, self.fan_int), -100.0) # clamp [-100, 100], lower/higher values are irrelevant
		speed = int(max(min(100.0, p + i), 0.0)) # clamp [0, 100]
		if speed <= 10:  # < 10% duty cycle doesn't work for the fan
			speed = 0
		return speed


	def perform_tasks(self):
		try:
			self.get_temperature()
			self.handle_fan()
		except Exception as e:
			self._logger.exception("Simple Chamber error: %s" % str(e))
			pass


	def dht_temp_callback(self, comm, parsed_temps):
		t = copy.deepcopy(parsed_temps)
		if self.last_dht_temp:
			t.update({ "C": (self.last_dht_temp, None) })
		return t


__plugin_name__ = "OctoPrint Simple Chamber"
__plugin_pythoncompat__ = ">=2.7,<4"
__plugin_implementation__ = SimpleChamber()
__plugin_hooks__ = {
	"octoprint.comm.protocol.temperatures.received": __plugin_implementation__.dht_temp_callback,
	"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
}

