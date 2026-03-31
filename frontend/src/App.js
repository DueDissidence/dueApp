import React, {useState, useEffect} from 'react';

import Toast from 'react-bootstrap/Toast';
import Container from 'react-bootstrap/Container';
import Stack from 'react-bootstrap/Stack';
import Card from 'react-bootstrap/Card';
import Moment from 'moment';

import './App.css';
import 'bootstrap-icons/font/bootstrap-icons.css';
import placeholder from './img/placeholder.jpg';

const Rant = ({ input }) => {
  const picture = input.profile_pic_url ? input.profile_pic_url : placeholder;
  const username = input.username;
  const amount = input.amount_dollars;
  const date = input.created_on;
  const text = input.text;

  const [copied, setCopied] = useState(false);
  const copy_text = `${username} ${amount}: ${text}`;

  const handleClose = () => {
    setCopied(true);
    navigator.clipboard.writeText(copy_text);
  };

  return (
    <Toast className={copied ? "faded" : ""}
           onClose={handleClose}
           key={!date}>
      <Toast.Header closeButton={true}>
        <img
          src={picture}
          className="rounded me-2"
          alt="profile"
          width={32}
          height={32}
        />
        <strong className="me-auto">
          {username} {amount}
        </strong>
        <small>{Moment(date).format("HH:mm")}</small>
      </Toast.Header>
      <Toast.Body>{text}</Toast.Body>
    </Toast>
  );
};

const App = () => {
  const [rants, setRants] = useState([])
  const [title, setTitle] = useState("No Livestream Found")
  const [likes, setLikes] = useState(0)
  const [watching, setWatching] = useState(0)

  const getData = async () => {
    try {
      const [rumbleResp, ytResp] = await Promise.all([
        fetch("/api/rants"),
        fetch("/api/youtube/superchats")
      ]);

      const rumble = await rumbleResp.json();
      const yt = await ytResp.json();

      let combined = [];

      if (rumble.status === 200) {
        const rumbleNormalized = (rumble.rants || []).map(r => ({
          profile_pic_url: r.profile_pic_url,
          username: r.username,
          amount_dollars: `$${(r.amount_cents / 100).toFixed(2)}`,
          created_on: r.created_on,
          text: r.text,
        }));
        combined = combined.concat(rumbleNormalized);
        setTitle(rumble.title);
        setLikes(rumble.likes);
        setWatching(rumble.watching);
      }

      if (yt.status === 200) {
        const ytNormalized = (yt.superchats || []).map(sc => ({
          profile_pic_url: sc.profileImageUrl,
          username: sc.author,
          amount_dollars: sc.amountMicros
            ? sc.amountDisplayString
            : sc.amountMicros / 1_000_000 || "",
          created_on: sc.publishedAt,
          text: sc.message,
        }));
        combined = combined.concat(ytNormalized);
      }

      combined.sort(
        (a, b) => new Date(b.created_on) - new Date(a.created_on)
      );

      setRants(combined);
    } catch (err) {
      console.error("Error fetching data", err);
    }
  };

  useEffect(() => {
    getData();
    const interval = setInterval(() => {
      getData();
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <Container className="p-3">
      <Container className="col-lg-8 p-5 mb-4 bg-light rounded-3">
        <Container className="row">
          <h1 className="header" key="header">Rumble Metrics</h1>
          <h2 className="header" key="subheader">{title}</h2>
          <Card className="col-lg-6" bg={"info"}>
            <Card.Body>
              <i className="bi bi-eye"></i> {watching}
            </Card.Body>
          </Card>
          <Card className="col-lg-6" bg={"info"}>
            <Card.Body>
              <i className="bi bi-hand-thumbs-up"></i> {likes}
            </Card.Body>
          </Card>
        </Container>
        <Container className="row p-2">
          <Stack className="rantstack flex-column-reverse" gap={2}>
            {rants.map((rant) => (
              <Rant key={rant.created_on} input={rant} />
            ))}
          </Stack>
        </Container>
      </Container>
    </Container>
  );
};

export default App;
