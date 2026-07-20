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
  const source = input.source;

  const headerClass =
    source === "youtube" ? "toast-header-youtube" : "toast-header-rumble";

  const [copied, setCopied] = useState(false);
  const copy_text = `${username} ${amount}: ${text}`;

  const handleClose = () => {
    setCopied(true);
    navigator.clipboard.writeText(copy_text);
  };

  return (
    <Toast className={copied ? "faded" : ""} onClose={handleClose} key={!date}>
      <Toast.Header closeButton={true} className={headerClass}>
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
  const [chatFilter, setChatFilter] = useState("rumble");
  const [rants, setRants] = useState([])
  const [title, setTitle] = useState("No Livestream Found")
  const [likes, setLikes] = useState(0)
  const [watching, setWatching] = useState(0)

  const visibleRants = rants.filter((rant) => {
    if (chatFilter === "all") return true;
    return rant.source === chatFilter;
  });

  const handleToggleButton = () => {
    setChatFilter((prev) => {
      if (prev === "all") return "youtube";
      if (prev === "youtube") return "rumble";
      return "all";
    });
  };

  const getData = async () => {
    try {
      const [rumbleResp, ytResp] = await Promise.all([
        fetch("/api/rants"),
        fetch("/api/youtube/superchats")
      ]);

      let combined = [];
      const rumble = await rumbleResp.json();
      const yt = await ytResp.json();

      if (rumble.status === 200) {
        const rumbleNormalized = (rumble.rants || []).map(r => ({
          source: "rumble",
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
          source: "youtube",
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
        (a, b) => new Date(a.created_on) - new Date(b.created_on)
      );

      setRants(combined);
    } catch (err) {
      console.error("Error fetching data", err);
    }
  };

  const getYouTubeID = async () => {
    try {
      await fetch("/api/youtube/streamid");
    } catch (err) {
      console.error("Error setting YouTube ID", err);
    }
  };

  // This occurs on page load.
  useEffect(() => {
    let interval;

    const init = async () => {
      try {
        await getYouTubeID();
      } catch (err) {
        console.error("YouTube ID init failed", err);
      }

      await getData();

      interval = setInterval(() => {
        getData();
      }, 30000);
    };

    init();

    return () => {
      if (interval) clearInterval(interval);
    };
  }, []);

  return (
    <Container className="p-3">

      <button type="button" onClick={handleToggleButton}>
        {chatFilter === "all"
          ? "Showing: All"
          : chatFilter === "youtube"
          ? "Showing: YouTube"
          : "Showing: Rumble"}
      </button>

      <Container className="col-lg-8 p-5 mb-4 bg-light rounded-3">
        <Container className="row">
          <h1 className="header" key="header">Stream Metrics</h1>
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
            {visibleRants.map((rant) => (
              <Rant key={`${rant.source}-${rant.username}-${rant.created_on}`} input={rant} />
            ))}
          </Stack>
        </Container>
      </Container>
    </Container>
  );
};

export default App;
