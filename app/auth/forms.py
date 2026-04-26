"""WTForms for authentication flows."""

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import (BooleanField, EmailField, PasswordField, SelectField,
                     StringField, TextAreaField)
from wtforms.validators import (DataRequired, Email, EqualTo, Length, Optional,
                                Regexp, ValidationError)

from app.models import User


class RegistrationForm(FlaskForm):
    name = StringField('Full Name', validators=[
        DataRequired(), Length(min=2, max=120)])

    email = EmailField('Email Address', validators=[
        DataRequired(), Email(), Length(max=120)])

    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, message='Password must be at least 8 characters.'),
        Regexp(r'^(?=.*[A-Za-z])(?=.*\d)',
               message='Password must contain letters and numbers.')])

    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(), EqualTo('password', message='Passwords must match.')])

    role = SelectField('Register As', choices=[
        ('vendor', 'Vendor / Bidder'),
        ('auditor', 'Auditor / Vigilance Officer'),
    ], validators=[DataRequired()])

    organization = StringField('Organization / Company Name', validators=[
        DataRequired(), Length(max=200)])

    phone = StringField('Phone Number', validators=[
        Optional(), Length(max=20)])

    gst_number = StringField('GST Number', validators=[
        Optional(), Length(max=20)])

    address = TextAreaField('Address', validators=[Optional(), Length(max=500)])

    digital_signature = FileField('Upload Digital Signature (optional)', validators=[
        Optional(),
        FileAllowed(['png', 'jpg', 'jpeg', 'pdf'], 'Images and PDFs only.')])

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data.lower()).first()
        if user:
            raise ValidationError('Email already registered. Please log in.')


class LoginForm(FlaskForm):
    email = EmailField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')


class PasswordResetRequestForm(FlaskForm):
    email = EmailField('Email Address', validators=[DataRequired(), Email()])


class PasswordResetForm(FlaskForm):
    password = PasswordField('New Password', validators=[
        DataRequired(), Length(min=8),
        Regexp(r'^(?=.*[A-Za-z])(?=.*\d)',
               message='Password must contain letters and numbers.')])
    confirm_password = PasswordField('Confirm New Password', validators=[
        DataRequired(), EqualTo('password')])


class ProfileUpdateForm(FlaskForm):
    name = StringField('Full Name', validators=[DataRequired(), Length(max=120)])
    organization = StringField('Organization', validators=[Optional(), Length(max=200)])
    phone = StringField('Phone', validators=[Optional(), Length(max=20)])
    address = TextAreaField('Address', validators=[Optional(), Length(max=500)])
    gst_number = StringField('GST Number', validators=[Optional(), Length(max=20)])
    pan_number = StringField('PAN Number', validators=[Optional(), Length(max=10)])
    digital_signature = FileField('Update Digital Signature', validators=[
        Optional(),
        FileAllowed(['png', 'jpg', 'jpeg', 'pdf'])])
