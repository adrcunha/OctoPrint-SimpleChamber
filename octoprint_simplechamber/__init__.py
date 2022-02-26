# coding=utf-8
from __future__ import absolute_import
import octoprint.plugin
import octoprint.util
import copy
import time
import Adafruit_DHT
import RPi.GPIO as GPIO
from octoprint.events import Events


class SimpleChamber(octoprint.plugin.StartupPlugin,
		    octoprint.plugin.RestartNeedingPlugin,
		    octoprint.plugin.SettingsPlugin,
		    octoprint.plugin.TemplatePlugin,
		    octoprint.plugin.EventHandlerPlugin,
		   ):

	platform = None
	last_dht_temp = None
	pwm = None
	fan_speed = 0
	fan_int = 0
	gpio_board_mode = True


	def get_pin(self, name):
		board_pin = int(self._settings.get([name + "_pin"]))
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
			fan_enabled=True,
			max_temp=30,
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


	def on_event(self, event, payload):
		if event == Events.CLIENT_OPENED:
			self._plugin_manager.send_plugin_message(self._identifier, dict(isFanEnabled=self._settings.get(["fan_enabled"])))
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

		fan_pin = self.get_pin("fan")
		GPIO.setup(fan_pin, GPIO.OUT)
		self.pwm = GPIO.PWM(fan_pin, 100)
		self.pwm.start(0)

		self.platform = Adafruit_DHT.common.get_platform() # Only do it once for speed sake.
		# DHTXX sensors are slow, sample every 2 seconds (DHT11 can be sampled every 1.5s)
		octoprint.util.RepeatedTimer(2.0, self.perform_tasks).start()

		self._logger.info("Simple Chamber started: sensor=%s, fan=%s" % (self._settings.get(["sensor_pin"]), fan_pin))


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
		sensor = Adafruit_DHT.DHT22 if int(self._settings.get(["sensor_type"])) == 22 else Adafruit_DHT.DHT11
		sensor_pin = int(self._settings.get(["sensor_pin"]))
		for i in range(0, 2):
			humidity, temperature = Adafruit_DHT.read(sensor, sensor_pin, self.platform)
			if humidity is not None and temperature is not None:
				break
		# Skip if error (it's fine, the temperature just won't update in the graph)
		self._logger.debug("H=%s T=%s sensor=%s sensor_pin=%s" % (humidity, temperature, sensor, sensor_pin))
		if humidity is None or temperature is None:
			return
		# Ignore subtle drops in temperature.
		# https://github.com/adafruit/Adafruit_Python_DHT/blob/master/Adafruit_DHT/common.py#L65
		if self.last_dht_temp and temperature - self.last_dht_temp <= -2:
				return
		self.last_dht_temp = temperature


	def handle_fan(self):
		if not self.last_dht_temp:
			return
		max_temp = float(self._settings.get(["max_temp"]))
		prev_speed = self.fan_speed
		self.fan_speed = self.get_fan_speed(self.last_dht_temp, max_temp)
		if not self._settings.get(["fan_enabled"]):
			self.pwm.ChangeDutyCycle(0)
			return
		if prev_speed != self.fan_speed:
			self._logger.info("Temperature is %.2fC, target is %.2fC, fan is now at %d%%" % (self.last_dht_temp, max_temp, self.fan_speed))
		if self.fan_speed > 0:
			if (prev_speed < 50 and self.fan_speed < prev_speed) or (prev_speed == 0 and self.fan_speed < 50):
				# Slowing down fan when alreayd at less than 50%, or starting from zero: "warm up" fan or it may stop
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


__plugin_pythoncompat__ = ">=2.7,<4"
__plugin_implementation__ = SimpleChamber()
__plugin_hooks__ = {
	"octoprint.comm.protocol.temperatures.received": __plugin_implementation__.dht_temp_callback,
	"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
}

