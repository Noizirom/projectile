"""
Projectile
2018 Nathan Craddock

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

bl_info = {
	"name": "Projectile",
	"author": "Nathan Craddock",
	"version": (1, 0),
	"blender": (2, 80, 0),
	"location": "3D View Sidebar > Physics tab",
	"description": "Set initial velocities for rigid body physics",
	"tracker_url": "",
	"category": "Physics"
}

# It might be cool to have a one-time handler for autoplayback

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
import mathutils
import math
from bpy.app.handlers import persistent


# Apply Transforms
def apply_transforms(context):
	for object in context.selected_objects:
		if object.projectile:
			# Setting r and s with auto update changes the second setting
			# Store for now
			location = object.location.copy()
			rotation = object.rotation_euler.copy()
			object.projectile_props.s = location
			object.projectile_props.r = rotation


def set_quality(context):
	frame_rate = bpy.context.scene.render.fps
	quality = context.scene.projectile_settings.quality
	if quality == 'low':
		context.scene.rigidbody_world.steps_per_second = frame_rate * 4
	elif quality == 'medium':
		context.scene.rigidbody_world.steps_per_second = frame_rate * 10
	elif quality == 'high':
		context.scene.rigidbody_world.steps_per_second = frame_rate * 20

	context.scene.rigidbody_world.solver_iterations = 20


def set_quality_callback(self, context):
	set_quality(context)


# Returns distance between two points in space
def distance_between_points(origin, destination):
	return math.sqrt(math.pow(destination.x - origin.x, 2) + math.pow(destination.y - origin.y, 2) + math.pow(destination.z - origin.z, 2))


# Raycast from origin to destination (Defaults to (nearly) infinite distance)
def raycast(origin, destination, distance=1.70141e+38):
	direction = (destination - origin).normalized()
	view_layer = bpy.context.view_layer

	cast = bpy.context.scene.ray_cast(view_layer, origin, direction, distance=distance)
	return cast


# Kinematic Equation to find displacement over time
# Used for drawing expected line
def kinematic_displacement_expected(initial, velocity, time):
	frame_rate = bpy.context.scene.render.fps

	if not bpy.context.scene.use_gravity:
		gravity = mathutils.Vector((0.0, 0.0, 0.0))
	else:
		gravity = bpy.context.scene.gravity


	dt = (time * 1.0) / frame_rate
	ds = mathutils.Vector((0.0, 0.0, 0.0))

	ds.x = initial.x + (velocity.x * dt) + (0.5 * gravity.x * math.pow(dt, 2))
	ds.y = initial.y + (velocity.y * dt) + (0.5 * gravity.y * math.pow(dt, 2))
	ds.z = initial.z + (velocity.z * dt) + (0.5 * gravity.z * math.pow(dt, 2))

	return ds


# Kinematic Equation with error correction
# Used for calulating keyframes on objects
def kinematic_displacement(initial, velocity, time):
	frame_rate = bpy.context.scene.render.fps

	if not bpy.context.scene.use_gravity:
		gravity = mathutils.Vector((0.0, 0.0, 0.0))
	else:
		gravity = bpy.context.scene.gravity

	dt = (time * 1.0) / frame_rate
	ds = mathutils.Vector((0.0, 0.0, 0.0))

	ds.x = initial.x + (velocity.x * dt) + (0.5 * gravity.x * math.pow(dt, 2))
	ds.y = initial.y + (velocity.y * dt) + (0.5 * gravity.y * math.pow(dt, 2))
	ds.z = initial.z + (velocity.z * dt) + (0.5 * gravity.z * math.pow(dt, 2))

	return ds


# Kinematic Equation to set angular velocity
def kinematic_rotation(initial, angular_velocity, time):
	frame_rate = bpy.context.scene.render.fps

	dt = (time * 1.0) / frame_rate
	dr = mathutils.Vector((0.0, 0.0, 0.0))

	dr.x = initial.x + (angular_velocity.x * dt)
	dr.y = initial.y + (angular_velocity.y * dt)
	dr.z = initial.z + (angular_velocity.z * dt)

	return dr


# Convert spherical to cartesian coordinates
def spherical_to_cartesian(radius, incline, azimuth):
	v = mathutils.Vector((0.0, 0.0, 0.0))

	v.x = radius * math.sin(incline) * math.cos(azimuth)
	v.y = radius * math.sin(incline) * math.sin(azimuth)
	v.z = radius * math.cos(incline)

	return v


# Convert cartesian to spherical coordinates
def cartesian_to_spherical(v):
	radius = math.sqrt(pow(v.x, 2) + pow(v.y, 2) + pow(v.z, 2))

	incline = 0
	if radius != 0:
		incline = math.acos(v.z / radius)

	azimuth = 0
	if v.x != 0:
		azimuth = math.atan(v.y / v.x)

	return radius, incline, azimuth


def calculate_trajectory(object):
	# Generate coordinates
	cast = []
	coordinates = []
	v = kinematic_displacement_expected(object.projectile_props.s, object.projectile_props.v, 0)
	coord = mathutils.Vector((v.x, v.y, v.z))
	coordinates.append(coord)

	for frame in range(1, bpy.context.scene.frame_end):
		v = kinematic_displacement_expected(object.projectile_props.s, object.projectile_props.v, frame)
		coord = mathutils.Vector((v.x, v.y, v.z))

		# Get distance between previous and current position
		distance = distance_between_points(coordinates[-1], coord)

		# Check if anything is in the way
		cast = raycast(coordinates[-1], coord, distance)

		# If so, set that position as final position (avoid self intersections)
		if cast[0] and cast[4] is not object:
			coordinates.append(cast[1])
			break

		coordinates.append(coord)
		coordinates.append(coord)

	if not cast[0]:
		v = kinematic_displacement_expected(object.projectile_props.s, object.projectile_props.v, bpy.context.scene.frame_end)
		coord = mathutils.Vector((v.x, v.y, v.z))
		coordinates.append(coord)

	return coordinates


# Functions for draw handlers
# Draws trajectories for all projectile objects
def draw_trajectory():
	objects = [object for object in bpy.data.objects if object.projectile]

	# Generate a list of all coordinates for all trajectories
	coordinates = []
	for object in objects:
		coordinates += calculate_trajectory(object)

	# Draw all trajectories
	# TODO: Fix shader being tied to annotations
	shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
	batch = batch_for_shader(shader, 'LINES', {"pos": coordinates})

	shader.bind()
	shader.uniform_float("color", (1, 1, 1, 1))

	batch.draw(shader)


# Removes draw handler when draw trajectories is disabled
def draw_trajectories_callback(self, context):
	if context.scene.projectile_settings.draw_trajectories:
		bpy.types.Scene.projectile_draw_handler = bpy.types.SpaceView3D.draw_handler_add(draw_trajectory, (), 'WINDOW', 'POST_VIEW')
	else:
		bpy.types.SpaceView3D.draw_handler_remove(bpy.types.Scene.projectile_draw_handler, 'WINDOW')


# Handler to run when UI property changes are made
def ui_prop_change_handler(*args):
	if bpy.context.scene.projectile_settings.draw_trajectories:
		draw_trajectory()

		# Tag View 3D to redraw if it is open
		for area in bpy.context.screen.areas:
			if area.type == 'VIEW_3D':
				area.tag_redraw()

	# run operator for each projectile object
	active = bpy.context.view_layer.objects.active

	for object in bpy.context.view_layer.objects:
		if object.projectile:
			bpy.context.view_layer.objects.active = object
			if bpy.context.scene.projectile_settings.auto_update:
				bpy.ops.rigidbody.projectile_launch()

	bpy.context.view_layer.objects.active = active


@persistent
def subscribe_to_rna_props(scene):
	bpy.types.Scene.props_msgbus_handler = object()

	# Subscribe to scene gravity changes
	subscribe_to = bpy.types.Scene, "gravity"
	bpy.msgbus.subscribe_rna(
		key=subscribe_to,
		owner=bpy.types.Scene.props_msgbus_handler,
		args=(),
		notify=ui_prop_change_handler,
	)

	# Subscribe to scene gravity toggle
	subscribe_to = bpy.types.Scene, "use_gravity"
	bpy.msgbus.subscribe_rna(
		key=subscribe_to,
		owner=bpy.types.Scene.props_msgbus_handler,
		args=(),
		notify=ui_prop_change_handler,
	)

	# Subscribe to scene frame rate changes
	subscribe_to = bpy.types.RenderSettings, "fps"
	bpy.msgbus.subscribe_rna(
		key=subscribe_to,
		owner=bpy.types.Scene.props_msgbus_handler,
		args=(),
		notify=ui_prop_change_handler,
	)


def unsubscribe_to_rna_props():
	# Unsubscribe from all RNA msgbus props
	bpy.msgbus.clear_by_owner(bpy.types.Scene.props_msgbus_handler)


class PHYSICS_OT_projectile_add(bpy.types.Operator):
	bl_idname = "rigidbody.projectile_add_object"
	bl_label = "Add Object"
	bl_description = "Set selected object as a projectile"

	@classmethod
	def poll(cls, context):
		if context.object:
			return context.object.type == 'MESH'

	def execute(self, context):
		for object in context.selected_objects:
			if not object.projectile:
				context.view_layer.objects.active = object
				# Make sure it is a rigid body
				if object.rigid_body is None:
					bpy.ops.rigidbody.object_add()

				# Set as a projectile
				object.projectile = True

				# Now initialize the transforms
				apply_transforms(context)

				# Set start frame
				object.projectile_props.start_frame = context.scene.frame_start

				# Make sure quality is set
				set_quality(context)

		return {'FINISHED'}


class PHYSICS_OT_projectile_remove(bpy.types.Operator):
	bl_idname = "rigidbody.projectile_remove_object"
	bl_label = "Remove Object"
	bl_description = "Remove object from as a projectile"

	@classmethod
	def poll(cls, context):
		if context.object:
			return context.object.projectile

	def execute(self, context):
		for object in context.selected_objects:
			if object.projectile:
				context.view_layer.objects.active = object

				# Remove animation data
				context.active_object.animation_data_clear()

				# Remove rigidbody if not already removed
				if bpy.context.object.rigid_body:
					bpy.ops.rigidbody.object_remove()

				context.object.projectile = False

				# HACKY! :D
				# Move frame forward, then back to update
				bpy.context.scene.frame_current += 1
				bpy.context.scene.frame_current -= 1

		return {'FINISHED'}


class PHYSICS_OT_projectile_apply_transforms(bpy.types.Operator):
	bl_idname = "rigidbody.projectile_apply_transforms"
	bl_label = "Apply Transforms"
	bl_description = "Set initial position and rotation to current transforms"

	@classmethod
	def poll(cls, context):
		if context.object.projectile:
			return context.object.type == 'MESH'

	def execute(self, context):
		# Apply transforms to all selected projectile objects
		apply_transforms(context)

		return {'FINISHED'}


# TODO: Rename?
class PHYSICS_OT_projectile_launch(bpy.types.Operator):
	bl_idname = "rigidbody.projectile_launch"
	bl_label = "Launch!"
	bl_description = "Launch the selected object!"

	@classmethod
	def poll(cls, context):
		if context.object:
			return context.object.type == 'MESH'

	def execute(self, context):
		object = context.object
		properties = object.projectile_props
		settings = bpy.context.scene.projectile_settings
		object.animation_data_clear()
		object.hide_viewport = False
		object.hide_render = False

		# Set start frame
		if bpy.context.scene.frame_start > properties.start_frame:
			properties.start_frame = bpy.context.scene.frame_start

		bpy.context.scene.frame_current = properties.start_frame

		displacement = kinematic_displacement(properties.s, properties.v, 2)
		displacement_rotation = kinematic_rotation(properties.r, properties.w, 2)

		# Hide object
		if properties.start_hidden:
			bpy.context.scene.frame_current -= 1
			object.hide_viewport = True
			object.hide_render = True
			object.keyframe_insert('hide_viewport')
			object.keyframe_insert('hide_render')

			bpy.context.scene.frame_current += 1
			object.hide_viewport = False
			object.hide_render = False
			object.keyframe_insert('hide_viewport')
			object.keyframe_insert('hide_render')

		# Set start keyframe
		object.location = properties.s
		object.rotation_euler = properties.r
		object.keyframe_insert('location')
		object.keyframe_insert('rotation_euler')

		bpy.context.scene.frame_current += 2

		# Set end keyframe
		object.location = displacement
		object.rotation_euler = displacement_rotation
		object.keyframe_insert('location')
		object.keyframe_insert('rotation_euler')

		# Set animated checkbox
		object.rigid_body.kinematic = True
		object.keyframe_insert('rigid_body.kinematic')

		bpy.context.scene.frame_current += 1

		# Set unanimated checkbox
		object.rigid_body.kinematic = False
		object.keyframe_insert('rigid_body.kinematic')

		bpy.context.scene.frame_current = 0

		if settings.auto_play and not bpy.context.screen.is_animation_playing:
			bpy.ops.screen.animation_play()

		return {'FINISHED'}


# A function to initialize the velocity every time a UI value is updated
def update_callback(self, context):
	if context.scene.projectile_settings.auto_update:
		bpy.ops.rigidbody.projectile_launch()
	return None


# A global to determine if the property is set from the UI to avoid recursion
FROM_UI = True

# Convert cartesian to spherical coordinates for the active object
def velocity_callback(self, context):
	global FROM_UI

	if FROM_UI:
		FROM_UI = False
		return

	ob = context.object

	if ob and ob.projectile:
		radius, incline, azimuth = cartesian_to_spherical(ob.projectile_props.v)

		FROM_UI = True
		ob.projectile_props.radius = radius
		FROM_UI = True
		ob.projectile_props.incline = incline
		FROM_UI = True
		ob.projectile_props.azimuth = azimuth

	# Run the launch operator
	update_callback(self, context)


# Convert spherical to cartesian coordinates for the active object
def spherical_callback(self, context):
	global FROM_UI

	if FROM_UI:
		FROM_UI = False
		return

	ob = context.object

	if ob and ob.projectile:
		radius = ob.projectile_props.radius
		incline = ob.projectile_props.incline
		azimuth = ob.projectile_props.azimuth

		FROM_UI = True
		ob.projectile_props.v = spherical_to_cartesian(radius, incline, azimuth)

	# Run the launch operator
	update_callback(self, context)


# TODO: Decide where to best place these settings (maybe two panels?) Quick settings in sidebar
# And detailed settings in physics tab
class PHYSICS_PT_projectile(bpy.types.Panel):
	bl_label = "Projectile"
	bl_category = "Physics"
	bl_space_type = "VIEW_3D"
	bl_region_type = "UI"

	def draw(self, context):
		layout = self.layout
		layout.use_property_split = True
		settings = context.scene.projectile_settings

		ob = context.object
		if (ob and ob.projectile):
			row = layout.row()
			if(len([object for object in context.selected_objects if object.projectile])) > 1:
				row.operator('rigidbody.projectile_remove_object', text="Remove Objects")
			else:
				row.operator('rigidbody.projectile_remove_object')

			if not settings.auto_update:
				row = layout.row()
				row.operator('rigidbody.projectile_launch')

		else:
			row = layout.row()
			if len(context.selected_objects) > 1:
				row.operator('rigidbody.projectile_add_object', text="Add Objects")
			else:
				row.operator('rigidbody.projectile_add_object')


class PHYSICS_PT_projectile_initial_settings(bpy.types.Panel):
	bl_label = "Initial Settings"
	bl_parent_id = "PHYSICS_PT_projectile"
	bl_category = "Physics"
	bl_space_type = "VIEW_3D"
	bl_region_type = "UI"
	bl_options = {'DEFAULT_CLOSED'}

	@classmethod
	def poll(self, context):
		if context.object and context.object.projectile:
			return True
		return False

	def draw(self, context):
		layout = self.layout
		layout.use_property_split = True
		object = context.object

		row = layout.row()
		row.prop(object.projectile_props, 'start_frame')

		row = layout.row()
		row.prop(object.projectile_props, 'start_hidden')

		row = layout.row()
		row.prop(object.projectile_props, 's')

		row = layout.row()
		row.prop(object.projectile_props, 'r')

		row = layout.row()
		row.operator('rigidbody.projectile_apply_transforms')


class PHYSICS_PT_projectile_velocity_settings(bpy.types.Panel):
	bl_label = "Velocity Settings"
	bl_parent_id = "PHYSICS_PT_projectile"
	bl_category = "Physics"
	bl_space_type = "VIEW_3D"
	bl_region_type = "UI"

	@classmethod
	def poll(self, context):
		if context.object and context.object.projectile:
			return True
		return False

	def draw(self, context):
		projectile_settings = context.scene.projectile_settings
		layout = self.layout
		layout.use_property_split = True
		object = context.object

		row = layout.row()
		row.prop(context.scene.projectile_settings, 'spherical')

		if projectile_settings.spherical:
			col = layout.column(align=True)
			col.prop(object.projectile_props, 'radius')
			col.prop(object.projectile_props, 'incline')
			col.prop(object.projectile_props, 'azimuth')
		else:
			row = layout.row()
			row.prop(object.projectile_props, 'v')

		row = layout.row()
		row.prop(object.projectile_props, 'w')


class PHYSICS_PT_projectile_settings(bpy.types.Panel):
	bl_label = "Projectile Settings"
	bl_parent_id = "PHYSICS_PT_projectile"
	bl_category = "Physics"
	bl_space_type = "VIEW_3D"
	bl_region_type = "UI"
	bl_options = {'DEFAULT_CLOSED'}

	@classmethod
	def poll(cls, context):
		for object in context.scene.objects:
			if object.projectile:
				return True

		return False

	def draw(self, context):
		layout = self.layout
		layout.use_property_split = True
		settings = context.scene.projectile_settings

		row = layout.row()
		row.prop(settings, "quality", expand=True)

		row = layout.row()
		row.prop(settings, "auto_update")

		row = layout.row()
		row.prop(settings, "auto_play")

		row = layout.row()
		row.prop(settings, 'draw_trajectories')


class ProjectileObjectProperties(bpy.types.PropertyGroup):
	start_frame: bpy.props.IntProperty(
		name="Start Frame",
		description="Frame to start velocity initialization on",
		default=1,
		options={'HIDDEN'},
		update=update_callback
	)

	s: bpy.props.FloatVectorProperty(
		name="Initial Location",
		description="Initial position for the object",
		subtype='TRANSLATION',
		precision=4,
		options={'HIDDEN'},
		update=update_callback
	)

	r: bpy.props.FloatVectorProperty(
		name="Rotation",
		description="Initial rotation for the object",
		precision=4,
		options={'HIDDEN'},
		subtype='EULER',
		update=update_callback
	)

	v: bpy.props.FloatVectorProperty(
		name="Velocity",
		description="Velocity for the object",
		subtype='VELOCITY',
		precision=4,
		options={'HIDDEN'},
		update=velocity_callback
	)

	w: bpy.props.FloatVectorProperty(
		name="Angular Velocity",
		description="Angular velocity for the object",
		subtype='EULER',
		precision=4,
		options={'HIDDEN'},
		update=update_callback
	)

	start_hidden: bpy.props.BoolProperty(
		name="Start Hidden",
		description="Hide the object before the start frame",
		default=False,
		options={'HIDDEN'},
		update=update_callback
	)

	radius: bpy.props.FloatProperty(
		name="Radius",
		description="Radius (magnitude) of velocity",
		default=0.0,
		unit='VELOCITY',
		update=spherical_callback
	)

	incline: bpy.props.FloatProperty(
		name="Incline",
		description="Incline (theta) for velocity",
		default=0.0,
		unit='ROTATION',
		update=spherical_callback
	)

	azimuth: bpy.props.FloatProperty(
		name="Azimuth",
		description="Azimuth (phi) for velocity",
		default=0.0,
		unit='ROTATION',
		update=spherical_callback
	)


class ProjectileSettings(bpy.types.PropertyGroup):
	draw_trajectories: bpy.props.BoolProperty(
		name="Draw Trajectories",
		description="Draw projectile trajectories in the 3D view",
		options={'HIDDEN'},
		default=True,
		update=draw_trajectories_callback
	)

	auto_update: bpy.props.BoolProperty(
		name="Auto Update",
		description="Update the rigidbody simulation after property changes",
		options={'HIDDEN'},
		default=True
	)

	auto_play: bpy.props.BoolProperty(
		name="Auto Play",
		description="Start animation playback after any changes",
		options={'HIDDEN'},
		default=False
	)

	quality: bpy.props.EnumProperty(
		name="Quality",
		items=[("low", "Low", "Use low quality solver settings"),
			   ("medium", "Medium", "Use medium quality solver settings"),
			   ("high", "High", "Use high quality solver settings")],
		default='medium',
		options={'HIDDEN'},
		update=set_quality_callback)

	spherical: bpy.props.BoolProperty(
		name="Spherical",
		description="Set velocity with spherical coordinates",
		options={'HIDDEN'},
		default=False
	)


classes = (
	ProjectileObjectProperties,
	ProjectileSettings,
	PHYSICS_PT_projectile,
	PHYSICS_PT_projectile_initial_settings,
	PHYSICS_PT_projectile_velocity_settings,
	PHYSICS_PT_projectile_settings,
	PHYSICS_OT_projectile_add,
	PHYSICS_OT_projectile_remove,
	PHYSICS_OT_projectile_launch,
	PHYSICS_OT_projectile_apply_transforms,
)


def register():
	from bpy.utils import register_class
	for cls in classes:
		register_class(cls)

	bpy.types.Scene.projectile_draw_handler = bpy.types.SpaceView3D.draw_handler_add(draw_trajectory, (), 'WINDOW', 'POST_VIEW')
	bpy.app.handlers.load_post.append(subscribe_to_rna_props)

	# Subscribe to properties on first install/register
	# Pass none to avoid argument count mismatch
	subscribe_to_rna_props(None)

	bpy.types.Object.projectile_props = bpy.props.PointerProperty(type=ProjectileObjectProperties)
	bpy.types.Scene.projectile_settings = bpy.props.PointerProperty(type=ProjectileSettings)
	bpy.types.Object.projectile = bpy.props.BoolProperty(name="Projectile")



def unregister():
	if bpy.types.Scene.projectile_draw_handler:
		bpy.types.SpaceView3D.draw_handler_remove(bpy.types.Scene.projectile_draw_handler, 'WINDOW')

	# Remove file load handler for subscribing
	bpy.app.handlers.load_post.remove(subscribe_to_rna_props)

	# Unsubscribe from rna props
	unsubscribe_to_rna_props()

	from bpy.utils import unregister_class
	for cls in reversed(classes):
		unregister_class(cls)

	del bpy.types.Object.projectile_props
	del bpy.types.Scene.projectile_settings
	del bpy.types.Object.projectile


if __name__ == "__main__":
	register()
